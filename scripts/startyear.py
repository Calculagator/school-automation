# Module: startyear.py
# contains functions/classes for using the Canvas API to manage observers and set course settings

from sqlalchemy.sql import func
from model import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, canvas_site, Session, crm_site
from time import ctime
import pandas  # for importing houses and attendance
import requests, json, sys
from urllib.parse import urlencode
zero_blanks = False
# search out phone numbers
import re
from dotenv import load_dotenv
from os import getenv
load_dotenv()

def get_grade_level(graduation_year, this_year = int(getenv("current_grad_year"))):
  return 12-(int(graduation_year)-this_year)

def convert_post_data(site):

  # passing a nested dict into the request data option mangles the json section
  # civicrm requires for sequential queries
  # processing with liburl works, but then additionally requires that 
  # content-type headers must be explicitly set to "application/x-www-form-urlencoded"
  # convert json's nested dict to str
  return urlencode(site.data).replace('%27','%22')


# remove all old observers? -
  # enrollment_type=ObserverEnrollment
# go through all students in local db, 
# find the corresponding parent in CRM, 
# create/update an observer account in canvas for each parent

def api_remove_observers(site = None):
  if not site:
    site=canvas_site()
  
  # get list of all observer ids
  url = site.baseUrl + f'accounts/{getenv("root_account")}/users?enrollment_type=observer&per_page=80'
  api_response = requests.get(url, headers=site.header, timeout=20)
  api_response.raise_for_status()  # exception if api call fails
  observer_ids = []
  while len(api_response.json()):

    # This response is not nested
    for user in api_response.json():
      observer_ids.append(user['id'])
    # go to the next link if there is one; break if there isn't or it's empty
    # should have multiple pages--too many for a 'last' link
    if api_response.links.get('next', 0):
      api_response = requests.get(
        api_response.links['next']['url'], headers=site.header, timeout=20)
    else:
      break
  # go through the id list and delete? all of the users

  for observer in observer_ids:
    url = site.baseUrl + f'accounts/{getenv("root_account")}/users/{observer}'
    attempts = 0
    while attempts < 3:
      try:
        api_response = requests.delete(url, headers=site.header, timeout=30)
        api_response.raise_for_status()  # exception if api call fails
        break
      except:
        attempts += 1
        print(f'Retrying user deletion for id {observer}')


def get_parent_id(site,parent):
  url = site.baseUrl + f'accounts/{getenv("root_account")}/users?search_term={parent.email}'
  api_response = requests.get(url, headers=site.header, timeout=30)
  try:
    parent_id = api_response.json()[0]['id']
  except:
    print(f'Unable to find user with email {parent.email}')
    parent_id = None
  return parent_id


def api_create_observers(site = None):
  if not site:
    site=canvas_site()

  session = Session()

  # ****************************************************************
  # Let's start with parents in the db first:

  parents = session.query(Parent).all() # easy to filter down to only current ones?
  for parent in parents:
    attempts = 0
    while attempts <3:
      try:
        # first find parent?
        parent_id = get_parent_id(site, parent)
        # if no parent in canvas, create one and grab the id
        if not parent_id:
          parent_name = parent.last_name + ', ' + parent.first_name
          url = site.baseUrl + f'accounts/{getenv("root_account")}/users?user[sortable_name]={parent_name}&pseudonym[unique_id]={parent.email}&user[skip_registration]=true'
          api_response = requests.post(url, headers=site.header, timeout=30)
          api_response.raise_for_status()  # exception if api call fails
          parent_id = api_response.json()['id']
        # Get all students to add
        print(f'Starting parent id {parent_id}')
        for student in parent.students:
          if student.active:
            # add all active students to parents - only active students should have parents, but check anyways
            st_attempts = 0
            while st_attempts <3:
              try:
                url2= site.baseUrl + f'users/{parent_id}/observees/{student.canvas_id}'
                api_response2 = requests.put(url2, headers=site.header, timeout=30)
                api_response2.raise_for_status()  # exception if api call fails
                break
              except:
                print(f'Problem with adding student {student.last_name}, {student.first_name} to parent id {parent_id}')
                st_attempts +=1
        print(f'Finished with parent {parent.last_name}, {parent.first_name}')
        break
      except:
        print(f'Problem with parent {parent.last_name}, {parent.first_name}')
        attempts +=1

def api_course_publish(site,course,grade_scale_id = None,home_page='feed', course_status = 'offer'):
  if not site:
    site=canvas_site()

# course[grading_standard_id]
# course[default_view]=feed
# course[event]=offer
  url = site.baseUrl + f'courses/{course.canvas_id}?' \
          + f'course[grading_standard_id]={grade_scale_id}' \
          + f'&course[default_view]={home_page}' \
          + f'&course[event]={course_status}' \
          + f'&course[hide_distribution_graphs]=true'
  try:
    api_response = requests.put(url, headers=site.header, timeout=20)
    api_response.raise_for_status()  # exception if api call fails
  except:
    print(f'Unable to update course {course.sis_id}')
def api_courses_update(site = None, term = None):
  if not site:
    site=canvas_site()
  session = Session()
  if not term:
    term=site.get_current_term()
  
  # get all courses in current term
  courses = session.query(Course).filter_by(term_id=term.term_id).all()
  for course in courses:
    if course.sis_id[6]=='L':
      api_course_publish(site,course,gs_grammar,'feed','offer')
    if course.sis_id[6]=='U':
      api_course_publish(site,course, gs_upper,'feed','offer')

def refresh_observers():
  api_remove_observers()
  api_create_observers()

def get_canvas_parent(site,email):
  # Returns the canvas id of user with given email or creates a user with given email if one does not already exit
  
  # Query canvas for a user with the given email
  url = site.baseUrl + f'accounts/{getenv("root_account")}/users?search_term={email}'
  api_response = requests.get(url, headers=site.header, timeout=30)
  try:
    parent_id = api_response.json()[0]['id']
    return parent_id
  except:
    # if user not found, make a new one
    print(f'Unable to find user with email {email}')
    try:
      session = Session()
      parent = session.query(Parent).filter_by(email=email).one()
      parent_name = parent.last_name + ', ' + parent.first_name
      url = site.baseUrl + f'accounts/{getenv("root_account")}/users?user[sortable_name]={parent_name}&pseudonym[unique_id]={parent.email}&user[skip_registration]=true'
      api_response = requests.post(url, headers=site.header, timeout=30)
      api_response.raise_for_status()  # exception if api call fails
      parent_id = api_response.json()['id']
      return parent_id
    except:
      print(f'Unable to create user')
      return None

def remove_observee(student_canvas_id,parent_email,site = None):
  if not site:
    site=canvas_site()

  parent_id=get_canvas_parent(site,parent_email)
  st_attempts = 0
  while st_attempts <3:
    try:
      url2= site.baseUrl + f'users/{parent_id}/observees/{student_canvas_id}'
      api_response2 = requests.delete(url2, headers=site.header, timeout=30)
      api_response2.raise_for_status()  # exception if api call fails
      break
    except:
      print(f'Problem with adding student to parent.')
      st_attempts +=1

def add_observee(student_canvas_id,parent_email, site = None):
  if not site:
    site=canvas_site()

  parent_id=get_canvas_parent(site,parent_email)
  st_attempts = 0
  while st_attempts <3:
    try:
      url2= site.baseUrl + f'users/{parent_id}/observees/{student_canvas_id}'
      api_response2 = requests.put(url2, headers=site.header, timeout=30)
      api_response2.raise_for_status()  # exception if api call fails
      break
    except:
      print(f'Problem with adding student to parent.')
      st_attempts +=1



def api_courses_stats(site = None,display_stats=False):
  if not site:
    site=canvas_site()
  if display_stats:
    hdg = 'false'
  else:
    hdg = 'true'
  session = Session()

  # get all courses
  courses = session.query(Course).all()
  for course in courses:
    url = site.baseUrl + f'courses/{course.canvas_id}/settings?' \
          + f'hide_distribution_graphs={hdg}'
    try:
      api_response = requests.put(url, headers=site.header, timeout=20)
      api_response.raise_for_status()  # exception if api call fails
    except:
      print(f'Unable to update stats {course.sis_id}')