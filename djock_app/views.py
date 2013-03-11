from django.http import HttpResponse
from django.shortcuts import render_to_response, render, redirect
from djock_app.models import Door, LockUser, RFIDkeycard, AccessTime, NewKeycardScan
import random
from datetime import datetime
from django.utils import simplejson
from termcolor import colored   # temp
from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.contenttypes.models import ContentType
from django.utils.encoding import force_unicode
from django.contrib.auth.models import User

# return list of rfid's allowed for all doors, or a particular door,
#   as json list 
def get_allowed_rfids(request, doorid=None):
    """ Returns list of allowed rfid's for the specified door, or 0 if none """
    # check that door id is valid. 
    #   Int of a certain length: taken care of in the urlconf
    #   Check that there even is a such 
    # if door id not valid, return ""
    doors = Door.objects.filter(pk=doorid)    # doorid should not be pk; note, get returns an rror if no such door; filter returns an empty list
    if doors:
        response = ",".join(doors[0].get_allowed_rfids())
    if not response: 
        response = 0  # make sure not going to return empty set
    return HttpResponse(response)


# TO DO: refactor below.. to return more immediately; 
#           clean up the conditional logic
def check(request,doorid, rfid): 
    """ In addition to checking whether the given rfid is valid for the given door, 
    also check whether we're actually trying to assign a new keycard rather than 
    authenticating. """
    response = 0
    # if door id not valid or rfid not valid, return ""

    # Is the request actually for new keycard assignment? 
    new_scan_queryset = NewKeycardScan.objects.all()
    if new_scan_queryset:
        new_scan = new_scan_queryset.latest("time_initiated")  # get the latest NewKeycardScan object, ordered by the field time_initiated (i.e. time the object was created) 
        # TODO: Things might go awry if someone else initiated a scan later... Currently verifying pk's later,  in
        # finished_keycard_scan, but do earlier. And pass pk info in a smarter way.

        if new_scan.waiting_for_scan == True:
            new_scan.doorid = doorid  # record the door the new scan request came from (not necessary so far) 
            new_scan.rfid = rfid
            new_scan.save()  
    
    # or is the request actually for authenticating an existing keycard for this door? 
    else: 
        rfidkeycard_list =  RFIDkeycard.objects.all()
        for rfidkeycard in rfidkeycard_list:
            allowed_doors = rfidkeycard.get_allowed_doors()
            if allowed_doors:
                for door in rfidkeycard.get_allowed_doors():
                    if rfidkeycard.is_active():
                        if rfidkeycard.the_rfid == rfid:
                            if int(door.id) == int(doorid):
                                response = 1

    return HttpResponse(response)

def initiate_new_keycard_scan(request,lockuser_object_id):
#def initiate_new_keycard_scan(request):

    # If this lockuser already has a current keycard, don't proceed
    # (This should have been prevented at template level also)
    try: 
        lu = LockUser.objects.filter(id=lockuser_object_id)
    except:
        response_data = {'success':False, "error_mess":"WTF? There's no lock user?"}
        return HttpResponse(simplejson.dumps(response_data), content_type="application/json")
    if lu[0].get_current_rfid():
        response_data = {'success':False, 'error_mess':"This lock user is already assigned a keycard! You shouldn't have even gotten this far!"} # Todo: So when stuff like this happens in production...  Should it sent some kind of automated error report to whomever is developing/maintaining the site? 
        return HttpResponse(simplejson.dumps(response_data), content_type="application/json")
    else:
        n = NewKeycardScan()
        n.waiting_for_scan = True
        n.assigner_user = request.user
        n.save()   
        response_data = {'success':True, 'new_scan_pk':n.pk}
        return HttpResponse(simplejson.dumps(response_data), content_type="application/json")
    
#def finished_new_keycard_scan(request, lockuser_object_id):
def finished_new_keycard_scan(request,new_scan_pk):
    """  Verify this is the NewKeycardScan object we initiated, that the rfid
        is not the same as that of a currently active keycard, and that we 
        haven't timed out. Then get the rfid from the newly-scanned card. 

        Also verifying __, ____, .........
    """
    # TODO:  raise exceptions.   
    # TODO:  Error codes to aid developers. So Staff user sees "ERROR (code 2). Try again," not "ERROR (scary message  about the exact error). Try again." 
    new_scan_queryset = NewKeycardScan.objects.all()
    if not new_scan_queryset:
        response_data = {'success':False, 'error_mess':"No NewKeycardScan objects at all"}
        return HttpResponse(simplejson.dumps(response_data), content_type="application/json")

    # Verify that the scan object is the one we need, not one initiated later by someone else, for example.
    new_scan_right_pk_qs = new_scan_queryset.filter(pk = new_scan_pk)  # make sure we have the newKeycardScan object we started with, not one that another staff user initiated *after* us. 

    if not new_scan_right_pk_qs:
        response_data = {'success':False, 'error_mess':"No NewKeycardScan obj with pk " + new_scan_pk}
        return HttpResponse(simplejson.dumps(response_data), content_type="application/json")

    new_scan = new_scan_right_pk_qs[0]
    min_till_timeout = 2
    timed_out, time_diff_minutes = new_scan.timed_out(minutes=min_till_timeout)
    if timed_out:
    #if new_scan.timed_out(minutes=min_till_timeout):
        response_data = {'success':False, 'error_mess':"Sorry, the system timed out. You have %d minutes to scan the card, then hit 'Done'.... So don't take %f minutes next time, please, fatty. Run to that lock! You could use the exercise." % (min_till_timeout,time_diff_minutes)}
        return HttpResponse(simplejson.dumps(response_data), content_type="application/json")

    if not new_scan.rfid:  
        response_data = {'success':False, 'error_mess':"NewKeycardScan does not have rfid"}
        return HttpResponse(simplejson.dumps(response_data), content_type="application/json")
    # if waiting for new keycard to be scanned, but timed out

    # Verify that the rfid is not the same as that of another ACTIVE keycard
    keycards_with_same_rfid_qs = RFIDkeycard.objects.filter(the_rfid=new_scan.rfid)
    for k in keycards_with_same_rfid_qs:
        if k.is_active():
            response_data = {'success':False, 'error_mess':"An active keycard with the same RFID is assigned to %s." % k.lockuser} # to do:  include actual link to this lockuser
            return HttpResponse(simplejson.dumps(response_data), content_type="application/json")


    # Verify that the lock user is associated with at least one door -- i.e. that at least one Door
    # checkbox is checked on the LockUser change_form
     
            
    # OK, so far so good. Set waiting and ready-to-assign status,
    # grab the assigner, and save NewKeycardScan object
    new_scan.waiting_for_scan = False
    new_scan.ready_to_assign = True 
    #new_scan.assigner_id = request.user.pk  # corresponding RFIDkeycard creation LogEntry needs the id of the logged-in user
    new_scan.assigner_user = request.user
    new_scan.save()

    response_data = {'success':True, 'rfid':new_scan.rfid}
    return HttpResponse(simplejson.dumps(response_data), content_type="application/json")


"""
# todo:  fix template stuff here. 
def deactivate_keycard(request,object_id):

    # object_id was in the url -- it contains the id of the lockuser that needs its
    #current keycard deactivated. 
    #    I.e. - get this lockuser's current keycard
    #         - deactivate it (set this keycard's date_revoked to now)

    # to do: exceptions
    try:
        lu = LockUser.objects.filter(id=object_id)[0]
        rfk = lu.get_current_rfid()
    except:
        # raise exception?
        return render(request,'basic.html') # ??????????????????????

    #if rfk.is_active():
        #rfk.date_revoked = datetime.now()
        #rfk.save()
    rfk.deactivate()


    # There are no LogEntry's for RFIDkeycard objects [since the User doesn't directly create RFIDkeycards
    # through the interface], so writing our own here. This will allow for RFIDkeycard.get_revoker() to
    # parallel RFIDkeycard.get_creator(). 
    # Todo:   ok to co-opt LogEntry here? Since 'deactivate keycard' is not actually a change on the
    # *RFIDkeycard* object, but on LockUser? 
    LogEntry.objects.log_action(
            user_id=request.user.pk,
            content_type_id=ContentType.objects.get_for_model(rfk).pk,
            object_id=rfk.id,  
            object_repr=force_unicode(rfk),
            action_flag=CHANGE,
            change_message="Deactivated keycard")  

    rfk.save()   # save RFIDkeycard object

    #return render(request, 'basic.html')
    #return HttpResponse(request,

    # back to the lockuser's (the one who we deactivated the card for) change_form
    back_to_lockuser = "/lockadmin/djock_app/lockuser/%s/" % lu.id
    return redirect(back_to_lockuser)
    #return redirect(lu)
"""
