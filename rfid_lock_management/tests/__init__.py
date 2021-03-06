# In order to avoid running all tests, import and specify on command line, e.g.
# $ ./manage.py test rfid_lock_management.DoorModelTests
from models_tests import *
from admin_tests import *
from functional_tests import *
from lock_comm_tests import *
from staff_users_tests import *
from views_tests import *
from functional_create_assign_walkthrough import *
from templatetags_tests import *
