# Module model.py
import string, secrets # generate passwords
import json  # used to read in the config file
import requests # api calls to canvas and crm
import re # match regular expressions
import sys # pull env variables etc.
import ftfy # unmangles text from web
import pandas # for reading attendance csv
import traceback # for error reporting
import dateutil # for easy converting dates to DateTime
from distutils.util import strtobool
from urllib.parse import urlencode
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Table, Column, Integer, Numeric, Unicode, DateTime, JSON, ForeignKey, Sequence, Boolean, or_, and_
from sqlalchemy.orm import relationship, sessionmaker, backref
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.sql.expression import literal_column
from dotenv import load_dotenv
from os import getenv
load_dotenv()

# Create an engine to connect to the database
# For now, I'm going to use a SQLite db
# engine = create_engine('sqlite:///:memory:', echo = True) # Change this as appropriate
engine = create_engine('sqlite:///records.db', echo=False)
# it will govern all db interactions in this module

Session = sessionmaker(bind=engine)

# Create a base class
Base = declarative_base()

# Create a Student class from the Base class mapped to a users table
# SQLite and PostgreSQL both allow for arbitrary string lengths. 
# If using another DB,the declaration would have to be like student_id=Column(Unicode(10))

# Table for multi to multi linking teachers and courses
course_teachers = Table('course_teachers', Base.metadata,
                        Column('course_id', Unicode,
                 ForeignKey('courses.sis_id')),
            Column('teacher_id', Unicode,
                 ForeignKey('teachers.sis_id'))
            )

# Table for linking students to parents
student_parents = Table('student_parents', Base.metadata,
            Column('student_id', Unicode,
                 ForeignKey('students.sis_id')),
            Column('parent_id', Unicode,
                 ForeignKey('parents.crm_id'))
            )

# Table for linking students to sections
student_sections = Table('student_sections', Base.metadata,
            Column('student_id', Unicode,
                 ForeignKey('students.sis_id')),
            Column('section_id', Unicode,
                 ForeignKey('sections.section_id'))
            )



class Student(Base):
  __tablename__ = 'students'
  # contains all students past and present
  # I'm making the sis_id be PK because old data may not have a canvas ID
  sis_id = Column(Unicode, primary_key=True)
  canvas_id = Column(Integer, unique=True)
  common_name = Column(Unicode)
  first_name = Column(Unicode)
  middle_name = Column(Unicode)
  last_name = Column(Unicode)
  birthday = Column(DateTime)
  gender = Column(Unicode)
  graduation_year = Column(Integer)
  house = Column(Unicode)
  active = Column(Boolean, default = False)
  password = Column(Unicode)
  email = Column(Unicode,unique=True)
  last_login = Column(DateTime)

  grade_records = relationship("Grade_Record", back_populates="student")
  attendance_records = relationship("Attendance", back_populates="student")
  parents = relationship("Parent", secondary = 'student_parents', back_populates="students")
  sections  = relationship("Section", secondary = 'student_sections', back_populates = "students")

  @hybrid_property
  def grade(self):

    # Integer grade level: K is 0 and JK is -1
    if getenv("current_grad_year"):
      grad_year = int(getenv("current_grad_year"))
    else:
      # graduation year rolls over June 1
      if datetime.now().month >= 6:
        grad_year = datetime.now().year + 1
      else:
        grad_year = datetime.now().year
    return 12-(self.graduation_year-grad_year)
    
  @grade.setter
  def grade(self,value):
    if value == None:
      print('Grade must have a value')
      return
    if not -1 <= value <=12:
      print('Grade must be between -1 and 12: no change has been made')
      return
    
    if getenv("current_grad_year"):
      grad_year = int(getenv("current_grad_year"))
    else:
      # graduation year rolls over June 1
      if datetime.now().month >= 6:
        grad_year = datetime.now().year + 1
      else:
        grad_year = datetime.now().year
    
    self.graduation_year = grad_year + 12 - value
  
  @staticmethod
  def get_grad_year(current_grade,current_grad_year = None):
    if not current_grad_year:
      current_grad_year = int(getenv("current_grad_year"))
    return current_grad_year + 12 - current_grade

  @staticmethod
  def get_grade_level(student_grad_year,current_grad_year = None):
    if not current_grad_year:
      current_grad_year = int(getenv("current_grad_year"))
    return current_grad_year + 12 - student_grad_year


  def push_to_canvas(self,*,canvas = None,add_missing = False):
    session = Session()
    student = session.merge(self)
    if not canvas:
      canvas = canvas_site()
    params = {'user[name]':f'{student.common_name} {student.last_name}',
              'user[short_name]':student.common_name,
              'user[sortable_name]':f'{student.last_name}, {student.common_name}',
              'user[email]':student.email
              }
    url = canvas.baseUrl + f'users/sis_user_id:{student.sis_id}'
    api_response = requests.put(url, headers=canvas.header, params=params, timeout=60)
    try:
      api_response.raise_for_status()
      if len(api_response.json()):
        student.canvas_id=api_response.json()['id']
        session.commit()
      elif add_missing:
        self.add_to_canvas(canvas = canvas)

    except Exception as e:
      print(e)
      print(api_response)
  
  def add_to_canvas(self,*,canvas = None):
    # adds student record to canvas
    session = Session()
    session.merge(self)
    if not canvas:
      canvas = canvas_site()
    params = {'user[name]':f'{self.common_name} {self.last_name}',
              'user[short_name]':self.common_name,
              'user[sortable_name]':f'{self.last_name}, {self.common_name}',
              'user[skip_registration]':True,
              'pseudonym[unique_id]':self.email,
              'pseudonym[sis_user_id]':self.sis_id,
              'pseudonym[authenticatio_provider_id]':"google",
              'enable_sis_reactivation':True}
    url = canvas.baseUrl + f'accounts/{getenv("root_account")}/users'
    
    try:
      api_response = requests.post(url, headers=canvas.header, params=params, timeout=60)
      api_response.raise_for_stats()
      user = api_response.json()
      self.canvas_id = user['id']
      session.merge(self)
      session.commit()

    except Exception as e:
      print(e)
      print(f'Error creating student {self.sis_id}')
      print(api_response)
    

  def update_canvas(self,*,canvas = None):
    # updates an existing student in Canvas
    if not canvas:
      canvas = canvas_site()
    
    params = {'user[name]':f'{self.common_name} {self.last_name}',
              'user[short_name]':self.common_name,
              'user[sortable_name]':f'{self.last_name}, {self.common_name}'}
    url = canvas.baseUrl + f'users/{self.canvas_id}'
    
    try:
      api_response = requests.put(url, headers=canvas.header, params=params, timeout=60)
      api_response.raise_for_status()
    except Exception as e:
      print(e)
      print(f'Error updating student {self.sis_id}')
      
  def gen_email(self,domain = None):
    # generates an email based on name and grad year, if it's unique, write it to the db and return it
    session = Session()
    student = session.merge(self)

    # quit if no grad year
    if not student.graduation_year:
      print(f'Student {student.sis_id} has not grad year')
      return False

    if not domain:
      domain = '@students.example.com'
    elif domain[0] != '@':
      domain = '@'+domain
    
    # first initial +last name
    lnamelen = 20
    fnamelen = 1
    fname = ''.join(re.findall(r'\w',student.common_name)).lower()
    lname = ''.join(re.findall(r'\w',student.last_name)).lower()
    
    try_count = 0
    while try_count < 3:
      email = fname[:fnamelen] +\
              lname[:lnamelen] +\
              str(student.graduation_year)[2:] +\
              domain
      try:
        student.email = email
        session.merge(student)
        session.commit()
        return email
      except IntegrityError:
        session.rollback()
        # should throw this exception if the email already exists in the db
        # add letters one at a time until we make it
        print(f'Collision with {email}')
        try_count += 1
        fnamelen += 1
        # input("Press Enter to continue...")
      except Exception as e:
        print(e)
  
  def update_parents(self,*,site = None,active = None):
    if not site:
      site = crm_site()
    session = Session()
    student = session.merge(self)
    parents = site.get_contacts_by_label('Student ID',self.sis_id)
    # this should be a list of all CRM contacts with a child matching the given student ID
    # we need to remove any old entries and update the new ones
    # if there is a list of contacts, then clear out old ones and add in new ones
    # this may need a cascading delete to clear out both the parent entry and the link 
    # -that could cause problems with other linked students
    # orphan parents shouldn't be a problem-maybe
    if 0 < len(parents) < 4: # should have more than 0 and 3 or fewer parents 
      student.parents.clear()
      # add in each parent entry
      # *** this needs a second api call to get all email/address info: the default only gives the first
      # for parents who are also teachers, we need the home email
      # we may also want to get multiple emails for sending reportcards
      for crm_parent in parents.values():

        phone = ''.join(re.findall(r'\d',crm_parent['phone']))

        parent = session.merge(Parent(
          crm_id=crm_parent['contact_id'], 
          first_name = crm_parent['first_name'], 
          last_name = crm_parent['last_name'], 
          email = crm_parent['email'], 
          phone = phone
          ))
        if active:
          parent.active = active
        session.merge(parent)
        student.parents.append(parent)
        
        
    session.commit()        

  def get_homeroom_teacher(self, term = None):
    # returns the first teacher object for the first homeroom in the specified period
    session = Session()
    site = canvas_site()
    if not term:
      term = site.get_current_term()
    
    # merge session
    student = session.merge(self)

    # match the first homeroom in the current term
    # if the course has no teachers, expect a nasty error
    for section in student.sections:
      if section.course.homeroom and section.course.term_id == term.term_id:
        return section.course.teachers[0]

  def update_house(self, site = None):
    # look up the house from crm and updates the DB
    if not site:
      site = crm_site()
    session = Session()
    student = session.merge(self)
    house = site.get_field_by_field("Student ID",student.sis_id,"House")
    if len(set(house)) > 1:
      print(f'Student with ID {student.sis_id} has multiple houses listed in CRM. Please update data in CRM')
    student.house = house[0]
    session.merge(student)
    session.commit()

  def update_grade(self, site = None):
    # Look up the grade level from crm and update the DB
    if not site:
      site = crm_site()
    session = Session()
    student = session.merge(self)
    grad_year = site.get_field_by_field(search_field_label="Student ID",
                                        search_value=student.sis_id,
                                        return_field_label="Grad Year")
    if len(set(grad_year)) > 1:
      print(f'Student with ID {student.sis_id} has multiple grades listed in CRM. Please update data in CRM')
    if not grad_year[0]:
      return False
    try:
      student.grad_year=int(grad_year[0])
    except:
      print(f'Student with ID {student.sis_id} could not set grade')
    session.merge(student)
    session.commit()

class Parent(Base):
  __tablename__ = 'parents'

  crm_id = Column(Unicode, primary_key=True)  # from CRM?
  canvas_id = Column(Integer, unique=True)
  first_name = Column(Unicode)
  last_name = Column(Unicode)
  email = Column(Unicode)
  password = Column(Unicode)
  phone = Column(Unicode)
  active = Column(Boolean, default = False)
  last_login = Column(DateTime)
  # I'd like a hybrid property? here that sets a parent active if they have active students
  # and inactive if they don't
  # or this could be set from School Status in crm directly
  students = relationship("Student", secondary = 'student_parents', back_populates="parents")

  def is_active(self,crm = None):
    # checks crm for School status - returns true for any with "current student"
    if not crm:
      crm = crm_site()
    # we have the crm id and are looking for School status

class Teacher(Base):
  __tablename__ = 'teachers'

  sis_id = Column(Unicode, primary_key=True)
  canvas_id = Column(Integer, unique=True)
  teacher_name = Column(Unicode)
  active = Column(Boolean, default = False)
  courses = relationship(
    "Course", secondary=course_teachers, back_populates="teachers")

class GP_Group(Base):
  __tablename__ = 'grading_period_groups'

  gp_group_id = Column(Integer, primary_key=True)
  gp_group_name = Column(Unicode)

  terms = relationship("Term", back_populates="gp_group")
  grading_periods = relationship("Grading_Period", back_populates="gp_group")

class Term(Base):
  __tablename__ = 'terms'

  term_id = Column(Integer, primary_key=True)
  term_name = Column(Unicode)
  gp_group_id = Column(Integer, ForeignKey(
    'grading_period_groups.gp_group_id'))

  gp_group = relationship("GP_Group", back_populates="terms")
  grade_records = relationship("Grade_Record", back_populates="term")
  courses = relationship("Course", back_populates="term")

  def export_attendance(self,*,filename = None,id_limit = 's1',grade_min = -1,grade_max = 12):
    # exports all attendance records for the period joined with students, attendance, teachers
    session = Session()
    term = session.merge(self)

    if not filename:
      filename = f'attendance {term.term_name}.xlsx'
    df = pandas.read_sql(
      session.query(
        Student.sis_id.label('student_id'), 
        Student.common_name,
        Student.last_name,
        Student.grade.label('grade_level'),
        Attendance.absences,
        Attendance.tardies,
        Grading_Period.period_name)
        .join(Student.attendance_records)
        .join(Attendance.grading_period)
        .filter(Student.sis_id.startswith(id_limit))
        .filter(Student.grade >= grade_min)
        .filter(Student.grade <= grade_max)
        .filter(Grading_Period.period_id >=4)
        .filter(Student.active == True).statement, 
        session.bind)
    df.to_excel(filename,f'attendance {term.term_name}')

  def export_classes(self,filename = None,*,id_limit = 's1',grade_min = -1,grade_max = 12, homeroom = True):
    # exports all student/coureses for the term joined with students, classes, teachers
    session = Session()
    term = session.merge(self)
   
    if not filename:
      filename = f'{term.term_name}.xlsx'
    df = pandas.read_sql(
      session.query(
        Student.sis_id.label('student_id'), 
        Student.common_name,
        Student.last_name,
        Student.grade.label('grade_level'),
        Section.section_name.label('section'),
        Teacher.teacher_name)
        .join(Term.courses)
        .join(Course.sections)
        .join(Section.students)
        .join(Course.teachers)
        .filter(Course.term_id == term.term_id)
        .filter(Student.sis_id.startswith(id_limit))
        .filter(Student.grade >= grade_min)
        .filter(Student.grade <= grade_max)
        .filter(Student.active == True)
        .filter(or_(Course.homeroom == homeroom,Course.homeroom == True)).statement, 
        session.bind)
    df.to_excel(filename,f'{term.term_name}')
  
  def export_grades(self,filename = None,*,id_limit = 's1',grade_min = 3,grade_max = 12):
    # exports all grade records for the period joined with students, classes, teachers
    session = Session()
    term = session.merge(self)

    # go through all periods of term
    # for each, create a subquery with student id, course id, score, letter - labeled by period name
    # create subquery for final
    # join all term subqueries together with final subquery
    # join with student name, teacher names, class names, etc
    gp_records = {}
    for grading_period in term.gp_group.grading_periods:
      gp_records[grading_period.period_name] = session.query(
        Grade_Record.student_id,
        Grade_Record.course_id,
        Grade_Record.score.label(f'{grading_period.period_name}_score'),
        Grade_Record.grade.label(f'{grading_period.period_name}_grade'),
        Grade_Record.comment.label(f'{grading_period.period_name}_comment')
        ).filter(Grade_Record.period_id == grading_period.period_id) \
        .filter(Grade_Record.midterm == False).subquery()
    
    # get final record
    frecord = session.query(
      Grade_Record.student_id,
        Grade_Record.course_id,
        Grade_Record.score.label(f'final_score'),
        Grade_Record.grade.label(f'final_grade')
        ).filter(Grade_Record.period_id == grading_period.get_term().term_id).subquery()
    
    # join in all period records
    for pname, precord in gp_records.items():
      frecord = session.query(
        frecord,
        precord
      ).outerjoin(precord,
        and_(
          frecord.c.student_id == precord.c.student_id,
          frecord.c.course_id == precord.c.course_id
        )).subquery()

    # join in all names
    full_query = session.query(
      Student.common_name,
      Student.last_name,
      Student.grade.label('grade_level'),
      Course.full_name.label('Course'),
      Course.print_name.label('Course short'),
      Teacher.teacher_name,
      frecord)\
      .join(Student)\
      .join(Course)\
      .join(Course.teachers)\
      .filter(Student.sis_id.startswith(id_limit))\
      .filter(Student.grade >= grade_min)\
      .filter(Student.grade <= grade_max)\
      .filter(Student.active == True)
    

    if not filename:
      filename = f'generated_docs/{term.term_name}/full term export.xlsx'
   

    df = pandas.read_sql(full_query.statement, session.bind)
    df.to_excel(filename,f'{term.term_name}')

  def update_enrollments(self,*, students = True, teachers = True, id_limit = ''):
    # updates all classes and enrollments for the period
    # now also updates all teachers
    session = Session()
    term = session.merge(self)

    for course in term.courses:
      # skip any courses without matching id
      if id_limit and id_limit not in course.sis_id:
        continue
      if students:
        course.update_enrollment()
      if teachers:
        course.update_teachers()
  
  def update_grade_records(self):
    # updates all grades for the period
    session = Session()
    term = session.merge(self)

    for course in term.courses:
      course.update_term_records()

  
  def add_courses(self, site=None, csv_name = None): #self uses info for calling object (current term id, etc)

    # this is a term method: it's not the place to check if we have the right term. 
    # That needs to happen where this is called.
    # this function should only work on itself
    #begin db session
    session = Session()

    accept = input (f'Add courses to term {self.term_name}? y/N  ')
    if not accept == 'y':
      print ("Term error. Aborting.")
      return
    
    # moved logic to add a term to the canvas_site class
    

    # Read data from file into data frame using Pandas
    
    if not csv_name:
      csv_name = f'courses {self.term_name}.csv'

    data = pandas.read_csv(csv_name, sep = ',')
    # Headers should be: 'course_id','print_name','full_name','account',
    # 'grading_standard', 'action'

    #convert dataframe to dictionary
    course_dict = data.to_dict(orient='records')
    print(f'There are {len(course_dict)} entries in {csv_name}')
  
    #Check whether correct number of courses has been loaded
    if not input ("Continue? y/N") == 'y':
      print("No changes made")
      return

    if not site:
      site = canvas_site()

    site.update_grading_standards()
    
    for course in course_dict:
      try:
        sis_id = course['course_id']
        full_name = course['full_name']
        if course['print_name']:
          print_name = course['print_name']
        else:
          print_name = full_name
        
        if course['grading_standard']:
          grading_standard_id = session.query(Grading_Standard)\
                            .filter_by(standard_title = course['grading_standard']).one().standard_id
        else:
          grading_standard_id = None
        
        if course['account']:
          canvas_id = session.query(Account)\
                            .filter_by(account_name = course['account']).one().canvas_id
        else:
          canvas_id = None
        
        if course['action'].lower() == 'create':
          site.create_course(sis_id = sis_id, full_name = full_name, account_id=canvas_id, print_name = print_name, term = self, grading_standard_id = grading_standard_id, default_view='Assignments')
      
      except Exception as e:
        print(e)
        print(f'Could not process line {course}')


class Grading_Period(Base):
  __tablename__ = 'grading_periods'

  period_id = Column(Integer, primary_key=True)
  period_name = Column(Unicode)
  gp_group_id = Column(Integer, ForeignKey('grading_period_groups.gp_group_id'))
  note_column = Column(Unicode)
  midterm_column = Column(Unicode)

  gp_group = relationship("GP_Group", back_populates="grading_periods")
  grade_records = relationship(
    "Grade_Record", back_populates="grading_period")
  attendance = relationship("Attendance", back_populates="grading_period")

  def get_term(self):
    session = Session()
    gp = session.merge(self)
    # I don't know why terms/periods are linked this way
    # could there ever be a time when a period belonged to more than one term?
    return gp.gp_group.terms[0]

  def get_comment_field(self,midterm = False):
    session = Session()
    self = session.merge(self)
    if not midterm:
      return self.note_column
    else:
      return self.midterm_column
  
  def set_comment_field(self,midterm,name = None):
    if not name:
      # generate a name by pulling the first letter and digit from the name + Comments
      # add an 'M' for midterm
      if not midterm: 
        field_name = re.search(r'[a-zA-Z]',self.period_name).group()+re.search(r'\d',self.period_name).group()+'Comments'
      else:
        field_name = re.search(r'[a-zA-Z]',self.period_name).group()+re.search(r'\d',self.period_name).group()+'M Comments'
    else:
      field_name = name
    # now that name is either given or set, write it to the db
    session = Session()
    # merge with external session?
    if not midterm:
      self.note_column = field_name
    else:
      self.midterm_column = field_name
    session.merge(self)
    session.commit()
    return field_name

  
  def activate_comments(self,site = None,*, midterm = False):
    # creates or makes the comment field visible and writeable for all courses in the term
    session = Session()
    # merge sessions
    self = session.merge(self)
    if not site:
      site = canvas_site()
    # title will vary for midterm/regular term
    # use the name from the DB if it exists
    # otherwise, generate and store it
    if not self.get_comment_field(midterm):
      self.set_comment_field(midterm)
    field_name = self.get_comment_field(midterm)

    # iterate through all courses in the grading period and activate their comments
    for term in self.gp_group.terms:
      for course in term.courses:
        course.custom_comments(field_name, hidden = False, read_only = False)

  def protect_comments(self,site = None,*, midterm = False):
    # creates or updates the comment field to be visible and read-only
    if not site:
      site = canvas_site()
    
    session = Session()
    # merge sessions
    self = session.merge(self)
    # title will vary for midterm/regular term
    # use the name from the DB if it exists
    # otherwise, generate and store it
    if not self.get_comment_field(midterm):
      self.set_comment_field(midterm)
    field_name = self.get_comment_field(midterm)

    # iterate through all courses in the grading period and protect their comments
    for term in self.gp_group.terms:
      for course in term.courses:
        course.custom_comments(field_name, hidden = False, read_only = True)

  def hide_comments(self,site = None,*, midterm = False):
    # creates or updates comments to be invisible and read-only
    if not site:
      site = canvas_site()
    session = Session()
    # merge sessions
    self = session.merge(self)
    # title will vary for midterm/regular term
    # use the name from the DB if it exists
    # otherwise, generate and store it
    if not self.get_comment_field(midterm):
      self.set_comment_field(midterm)
    field_name = self.get_comment_field(midterm)

    # iterate through all courses in the grading period and activate their comments
    for term in self.gp_group.terms:
      for course in term.courses:
        course.custom_comments(field_name, hidden = True, read_only = True)

  def update_attendance(self,filename = None):
    # reads attendance data for a grading_period from the given file
    # start and merge session
    session = Session()
    period = session.merge(self)

    # clear out old records for the period
    session.query(Attendance).filter_by(period_id = period.period_id).delete()
    session.commit()
    # if the filename isn't given, guess based on the pattern f'{period_name} attendance.csv'
    if not filename:
      filename = f'attendance/{period.get_term().term_name}/{period.period_name}.csv'

    # bypass csv module and go straight to a dataframe:
    # only need the two columns
    # .apply(lambda x: x.astype(str).str.lower()) makes everything lowercase
    try:
      df = pandas.read_csv(filename, usecols=['ID','STATUS']).apply(lambda x: x.astype(str).str.lower())
    except:
      print('Unable to load attendance')
      return
    # make a pivot table and count number of each status per ID
    a_count=df.pivot_table(index='ID',columns='STATUS',aggfunc='size',fill_value=0)
    for row in a_count.itertuples():
      # only actual students with id's
      if row.Index[0] != 's':
        continue
      
      a_record=Attendance(student_id=row.Index,period_id=period.period_id)
      # half-days get labeled as _1
      a_record.absences = row.absent + 0.5*row._1
      a_record.tardies = row.tardy
      session.merge(a_record)
      session.commit()
  
  def update_grade_records(self,*,midterm = False, comments = True, id_limit = ''):
    # updates all grades for the period
    session = Session()
    period = session.merge(self)
    # there is probably one one term- but it still gives a list
    for term in period.gp_group.terms:
      for course in term.courses:
        # skip courses not matching limit
        if id_limit and id_limit not in course.sis_id:
          continue
        if midterm:
          course.update_midterm_records(period, comments=comments)
        else:
          course.update_trimester_records(period, comments=comments)
  
  def export_xls(self,filename = None,*,midterm = False,id_limit = 's1',grade_min = 3,grade_max = 12):
    # exports all grade records for the period joined with students, classes, teachers
    session = Session()
    period = session.merge(self)

    if not filename:
      filename = f'{period.period_name}.xlsx'
    df = pandas.read_sql(
      session.query(
        Student.sis_id.label('student_id'), 
        Student.common_name,
        Student.last_name,
        Student.grade.label('grade_level'),
        Grade_Record.score,
        Grade_Record.grade,
        Grade_Record.comment,
        Course.full_name.label('course'),
        Course.sis_id.label('course_id'))
        .join(Grade_Record.student)
        .join(Grade_Record.course)
        .filter(Grade_Record.period_id == period.period_id)
        .filter(Grade_Record.student_id.startswith(id_limit))
        .filter(Student.grade >= grade_min)
        .filter(Student.grade <= grade_max)
        .filter(Grade_Record.midterm == midterm).statement, 
        session.bind)
    df.to_excel(filename,f'{period.period_name}')

class Section(Base):
  __tablename__ = 'sections'
  section_id = Column(Unicode, primary_key=True)
  section_name = Column(Unicode)
  course_id = Column(Unicode, ForeignKey('courses.sis_id',onupdate="CASCADE", ondelete="CASCADE"))
 
  students = relationship("Student", secondary = student_sections, back_populates = "sections", order_by = "Student.last_name")
  course = relationship("Course", back_populates = 'sections')

  # I'd like a method to delete empty course sections

class Course(Base):
  __tablename__ = 'courses'

  canvas_id = Column(Integer, unique=True)
  sis_id = Column(Unicode, primary_key=True)
  term_id = Column(Integer, ForeignKey('terms.term_id'))
  full_name = Column(Unicode)
  print_name = Column(Unicode)
  account_id = Column(Unicode, ForeignKey('accounts.sis_id'))
  standard_id = Column(Unicode, ForeignKey('grading_standards.standard_id'))
  homeroom = Column(Boolean, default = False)

  teachers = relationship(
    "Teacher", secondary=course_teachers, back_populates="courses")
  
  term = relationship("Term", back_populates="courses")
  grade_records = relationship("Grade_Record", back_populates="course")
  sections = relationship("Section", back_populates = "course")
  grading_standard = relationship('Grading_Standard', back_populates = "courses")
  account = relationship('Account', back_populates = 'courses')

  def update_canvas(self,*,site=None,home=None,status='offer',stats=False,guess_grading_standard=True):
    # home options are - feed, wiki, modules (must exist), assignments, syllabus
    # statuses - claim = unpublish, offer = publish, conclude makes read-only, delete, undelete
    if not site:
      site = canvas_site()
    
    session = Session()
    course = session.merge(self)
    # start building params - always include status
    params = {
      'course[event]':status
    }
    if not stats:
      params['course[hide_distribution_graphs]'] = True

    if guess_grading_standard:

      try:
        if course.standard_id:
          params['course[grading_standard_id]']=course.standard_id
        # use list slices to avoid index out of bounds
        elif course.sis_id[6:7] == 'F':
          std_id = session.query(Grading_Standard).filter_by(standard_title='Pass/Fail').one().standard_id
          params['course[grading_standard_id]']=std_id
        elif course.sis_id[6:7] == 'U':
          std_id = session.query(Grading_Standard).filter_by(standard_title='Upper School').one().standard_id
          params['course[grading_standard_id]']=std_id
        elif course.sis_id[6:7] == 'G':
          std_id = session.query(Grading_Standard).filter_by(standard_title='Grammar School').one().standard_id
          params['course[grading_standard_id]']=std_id
        elif course.sis_id[6:7] == 'P':
          std_id = session.query(Grading_Standard).filter_by(standard_title='Primary School').one().standard_id
          params['course[grading_standard_id]']=std_id
        else:
          print(f'Unable to determine grading scale for course {course.sis_id}')
      except Exception as e:
        print(e)
    if home:
      params['course[default_view]']=home
    try:
      url = site.baseUrl + f'courses/{course.canvas_id}'
      api_response = requests.put(url, headers=site.header, params=params, timeout=60)
      api_response.raise_for_status()
      if not api_response.json()["workflow_state"]=='available':
        print(f'Course {api_response.json()["sis_course_id"]} is {api_response.json()["workflow_state"]} with home {api_response.json()["default_view"]}')

      # I could/should add a check to ensure publication
      # course may fail to publish if it has a currently invalid home
      # create a module and welcome message for courses that don't have one?

    except Exception as e:
      print(e)
      
  
  def get_canvas_tab_id(self,*,name = None, site = None):
    # returns the tab id for the given name in the course
    # this function is mostly superfluous since tab ids are mostly hard-coded strings
    # use default site
    if not site:
      site = canvas_site()
    
    # default name is "Modules"
    if not name:
      name = "Modules"
    # query the api
    # no parameters for this request- should return all tabs in a single request
    url = self.baseUrl + f'courses/{self.canvas_id}/tabs'
    for tab in requests.get(url, headers=self.header, timeout=60).json():
      if tab['label'] == name:
        return tab['id']

  def set_canvas_tab_params(self,*,tab_id = None,site = None,position = None, hidden = 'false'):
    # moves the given tab for the site and course to the position

    # default site
    if not site:
      site = canvas_site()
    
    # default id is "modules"
    if not tab_id:
      tab_id = 'modules'

    # default position is 1
    if not position:
      position = 2

    params = {'position':position,
              'hidden':hidden,
              'visibility':'members'}
    url = site.baseUrl + f'courses/{self.canvas_id}/tabs/{tab_id}'
    api_response = requests.put(url, headers=site.header, params=params, timeout=60)
    try:
      api_response.raise_for_status()
    except Exception as e:
      print(e)

  def set_canvas_course_home_tab(self,*,site = None, tab_id = None):
    # sets the given tab_id as the "default_view" for the given course

    # default site
    if not site:
      site = canvas_site()

    # default id is "modules"
    if not tab_id:
      tab_id = 'modules'

    params = {'course[default_view]':tab_id}
    url = site.baseUrl + f'courses/{self.canvas_id}'
    api_response = requests.put(url, headers=site.header, params=params, timeout=60)
    try:
      api_response.raise_for_status()
    except Exception as e:
      print(e) 
  
  def set_homeroom_guess(self):
    # guesses if the course is a homeroom using Primary classes or Classical Studies
    session = Session()
    course = session.merge(self)
    if "Classical Studies" in course.full_name:
      course.homeroom = True
    elif "Classical Christian Studies" in course.full_name:
      course.homeroom = True
    elif len(course.sis_id) > 7 and course.sis_id[6] == "P":
      course.homeroom = True
    else:
      course.homeroom = False
    session.commit()
    return course.homeroom
  
  def hide_stats(self,site = None):
    if not site:
      site = canvas_site()
    url=site.baseUrl + f'courses/{self.canvas_id}/settings?hide_distribution_graphs=true'
    # response looks like:
    # [{"id":12,"title":"T1Comments","position":1,"teacher_notes":false,"read_only":true,"hidden":false},
    # {"id":161,"title":"T2Comments","position":2,"teacher_notes":false,"read_only":false,"hidden":false}]
    api_response = requests.put(url, headers = site.header, timeout=60)
    api_response.raise_for_status()
  
  def update_teachers(self,site = None):
    
    if not site:
      site = canvas_site()
    session = Session()
    # must merge sessions since Course is from an external session
    course = session.merge(self)
    # clear out any old teachers?
    course.teachers.clear()
    url = site.baseUrl + f'/courses/{course.canvas_id}/enrollments?type[]=TeacherEnrollment'
    api_response = requests.get(url, headers=site.header, timeout=60)
    api_response.raise_for_status()  # exception if api call fails
    
    while len(api_response.json()):

      # This response is not nested
      for user in api_response.json():
        # Must have a sis_id
        try:
          teacher=session.query(Teacher).filter_by(sis_id=user['sis_user_id']).one()
          if teacher not in course.teachers:
            course.teachers.append(teacher)
        except KeyError:
          # probably can't find a sis_id
          print(f'The course {course.full_name} experienced an API error with teacher enrollments!')
          continue
        except:
          print("Error:",sys.exc_info()[0],"occured.")
          continue

      # go to the next link if there is one; break if there isn't or it's empty
      # should have multiple pages, but probably still has a 'last' link
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=site.header, timeout=60)
      else:
        break
    session.commit()  

  def update_enrollment(self,site = None):
    # pulls all sections and their respective enrolled students from canvas
    # loop through to add each section and then loop through the students to add each
    if not site:
      site = canvas_site()

    # Merge with external session:
    session = Session()
    course = session.merge(self)
    
    # clear out all old enrollments for the course
    # leave orphan sections
    for section in course.sections:
      section.students.clear()
    
    
    url = site.baseUrl + \
    f'courses/{course.canvas_id}/sections?include[]=students&per_page=80'
    # pulls 80 responses at a time instead of default 10
    try:
      api_response = requests.get(url, headers=site.header, timeout=60)
      api_response.raise_for_status()  # exception if api call fails
      
      while len(api_response.json()):

        # This response is not nested
        for section in api_response.json():
          try:
            # only mess with sections that have students
            if section.get('students'):
              # courses added via the web ui must have sis_id added or they will be skipped
              if not section.get('sis_course_id'):
                print(f'Unable to add section because course {section["course_id"]} is missing a SIS ID')
                continue
              
              section_db = session.merge(Section(section_id=section['id'],
                        section_name=section['name'],
                        course_id=section['sis_course_id']))
              for student in section['students']:
                # skip any non SIS students - this should exist but be blank
                if not student['sis_user_id']:
                  print(f'Studnt {student["name"]} with canvas id {student["id"]} does not have a student ID')
                  continue
                
                try:
                  student_db=session.query(Student).filter_by(sis_id=student['sis_user_id']).one_or_none()

                  # skip any students not in the DB
                  if not student_db:
                    # print(f'Student {student["name"]} with sis id {student["sis_user_id"]} has not been imported from CRM')
                    continue
              
                  # set enrolled student to active
                  # student_db.active = True
                  if student_db not in section_db.students: # must not already exist in db
                    section_db.students.append(student_db)
                except:
                  print(f'Problem with student {student["name"]} with canvas id {student["id"]}. Could not add to {course.sis_id}')
              session.commit()
          except:
            print(f'Problem with section {section["name"]}')

        # go to the next link if there is one; break if there isn't or it's empty
        # should have multiple pages, but probably still has a 'last' link
        if api_response.links.get('next', 0):
          api_response = requests.get(
            api_response.links['next']['url'], headers=site.header, timeout=60)
        else:
          break
    except Exception as e:
        print(e)
        print(url)

  def custom_comments(self,field_name,*, hidden = True, read_only = True):
    # Activates the custom column with the name given in the DB or creates it if it doesn't exist
    site=canvas_site()

    #api call might be case sensitive for true/false
    hidden = f'{hidden}'.lower()
    read_only = f'{read_only}'.lower()
 
    # get a list of note columns to check if ours exists yet
    url=site.baseUrl + f'courses/{self.canvas_id}/custom_gradebook_columns?include_hidden=true&per_page=80'
    # response looks like:
    # [{"id":12,"title":"T1Comments","position":1,"teacher_notes":false,"read_only":true,"hidden":false},
    # {"id":161,"title":"T2Comments","position":2,"teacher_notes":false,"read_only":false,"hidden":false}]
    api_response = requests.get(url, headers = site.header, timeout=60)
    api_response.raise_for_status()
    
    # let's add a bool for if we've found the column we want
    notes_exist = False
    while len(api_response.json()):
      # This response is not nested
      for column in api_response.json():
          # check if this column matches the one we need
          if column['title'] == field_name:
              # we found it- so no need to create it
              notes_exist = True
              # I could check if it's hidden or read only, but that would take an API call anyways -
              # instead, I'll just make it visible and writeable according to inputs
              urlup = site.baseUrl + f"courses/{self.canvas_id}/custom_gradebook_columns/{column['id']}?column[teacher_notes]=false&column[read_only]={read_only}&column[hidden]={hidden}"
              requests.put(urlup, headers = site.header, timeout=60)
              print(f'{field_name} for course {self.full_name} set to read_only={read_only} and hidden={hidden}')
      
      # go to the next link if there is one; break if there isn't or it's empty
      # should not be needed
      if api_response.links.get('next',0):
          api_response = requests.get(api_response.links['next']['url'], headers=site.header, timeout=60)
      else:
          break
    
    # If we haven't found it, we need to add it with a post instead of put
    if not notes_exist:
      urlup = site.baseUrl + f"courses/{self.canvas_id}/custom_gradebook_columns?column[teacher_notes]=false&column[read_only]={read_only}&column[title]={field_name}&column[hidden]={hidden}"
      requests.post(urlup, headers = site.header, timeout=60)
      print(f'Created {field_name} for course {self.full_name}')  

  def update_period_grades(self,period = None, midterm = False):
    # pulls the grade records for the given/current period from canvas
    # setting midterm to true clears midterm records and stores midterm records
    # start and merge sessions
    session = Session()
    course = session.merge(self)
    # get the current period if not given
    site = canvas_site()
    if not period:
      period = site.get_current_period()
    
    # clear out previous grade records for this period from the session/db
    session.query(Grade_Record).filter_by(course_id = course.sis_id).filter_by(period_id = period.period_id).filter_by(midterm = midterm).delete()
    session.commit()
    # import the desired behavior for blanks:
    blanks_are_zero = strtobool(getenv('zero_blanks'))
    
    if blanks_are_zero:
        score='final_score'
        grade='final_grade'
    else:
        score='current_score'
        grade='current_grade'

    # API request to Canvas pulls grades for the period
    url=site.baseUrl +(
    f'courses/{course.canvas_id}/enrollments?'
    'per_page=80&type[]=StudentEnrollment'
    f'&grading_period_id={period.period_id}'
    )
    api_response = requests.get(url, headers = site.header, timeout=120)
    api_response.raise_for_status()

    while len(api_response.json()):
        # This response is not nested
        for record in api_response.json():
          # check for pass/fail
          # many will be blank
          if not record['grades'][grade]:
            rec_grade = 'Pass'
            rec_score = None
          
          # some will have a grade
          elif record['grades'][grade] in ['Pass','pass','Fail','fail']:
            rec_grade = record['grades'][grade]
            rec_score = None
          
          # the rest (most)
          else:
            rec_grade = record['grades'][grade]
            rec_score = record['grades'][score]
          
          
          session.add(Grade_Record(student_id=record['user']['sis_user_id'],
                                      period_id=period.period_id,
                                      course_id=course.sis_id,
                                      score=rec_score,
                                      grade=rec_grade,
                                      quality_points=Grade_Record.get_quality_points(record['grades'][grade]),
                                      midterm = midterm))
          session.commit()
        # go to the next link if there is one; break if there isn't or it's empty
        # should not be needed
        if api_response.links.get('next',0):
            api_response = requests.get(api_response.links['next']['url'], headers=site.header, timeout=60)
        else:
            break

  def update_period_comments(self,period = None, midterm = False):
    # pulls the comments for the given/current period from canvas and updates any existing grade records
    # setting midterm to true clears midterm records and stores midterm records
    # start and merge sessions
    session = Session()
    course = session.merge(self)
    # get the current period if not given
    site = canvas_site()
    if not period:
      period = site.get_current_period()
    session.merge(period)
    # check if any grade records exist and pull; exit if they don't
    if not session.query(Grade_Record).filter_by(course_id = course.sis_id).filter_by(period_id = period.period_id).filter_by(midterm = midterm).all():
      print(f'No grade records exist for course {course.full_name}. Please pull grade records before comments')
      return
    
    # query notes for the course/period from canvas
    # get the field_name for our comments from the db
    field_name = period.get_comment_field(midterm)
    # check if field_name is valid
    if not field_name:
      print(f'It look like the comments field has not yet been set for period {period.period_name}. Attempting to guess the appropriate field . . .')
      field_name = period.set_comment_field(midterm)
      session.merge(period)
      session.commit()
    # get a list of note columns to check if ours exists yet
    url=site.baseUrl + f'courses/{course.canvas_id}/custom_gradebook_columns?include_hidden=true'
    # response looks like:
    # [{"id":12,"title":"T1Comments","position":1,"teacher_notes":false,"read_only":true,"hidden":false},
    # {"id":161,"title":"T2Comments","position":2,"teacher_notes":false,"read_only":false,"hidden":false}]
    
    # if getting these comment fields fails, something is wrong. It's probably not helpful to retry
    attempts = 0
    while attempts < 3:
      try:
        api_response = requests.get(url, headers = site.header, timeout=20)
        api_response.raise_for_status()
      
        while len(api_response.json()):
          # This response is not nested
          for column in api_response.json():
            # check if this column matches the one we need
            if column['title'] == field_name:
              # we found it- now pull all comments from it

              urlup = site.baseUrl + f'courses/{course.canvas_id}/custom_gradebook_columns/{column["id"]}/data?include_hidden=true&per_page=80'
              api_response_comments = requests.get(urlup, headers = site.header, timeout=60)
              api_response_comments.raise_for_status()
              while len(api_response_comments.json()):
                # This response is not nested
                for note in api_response_comments.json():
                  # notes use canvas id's so we need to look those up for the given students
                  try:
                    student=session.query(Student).filter_by(canvas_id=note['user_id']).one()
                    grade_record = session.query(Grade_Record).\
                      filter_by(student_id=student.sis_id).\
                      filter_by(course_id=course.sis_id).\
                      filter_by(period_id=period.period_id).\
                      filter_by(midterm = midterm).one()
                    grade_record.comment = ftfy.fix_text(note['content'])
                    session.merge(grade_record)
                    session.commit()
                  except Exception as e:
                    print(e)
                    print(f'Problem with setting the comment')
                    print(f'Course {course.full_name}')
                    print(f'Student ID {note["user_id"]}')
                    print(note)
                # go to the next link if there is one; break if there isn't or it's empty
                # should not be needed
                if api_response.links.get('next',0):
                    api_response = requests.get(api_response.links['next']['url'], headers=site.header, timeout=60)
                else:
                    break
              # Stop processing api junk after comments are updated
              return
          # go to the next link if there is one; break if there isn't or it's empty
          # should not be needed
          if api_response.links.get('next',0):
              api_response = requests.get(api_response.links['next']['url'], headers=site.header, timeout=20)
          else:
              break
        break
      except Exception as e:
        print(e)
        print(url)
        attempts += 1

  def update_trimester_records(self,period = None,*,comments = True):
    # updates trimester/period grade_records for printing reports
    self.update_period_grades(period,midterm = False)
    if comments:
      self.update_period_comments(period,midterm = False)

  def update_midterm_records(self,period = None,*, comments = True):
    # pulls current grades for the given/current period and stores them to the DB
    self.update_period_grades(period,midterm = True)
    if comments:
      self.update_period_comments(period,midterm = True)
 
  def update_term_records(self,term = None):
    # pulls the grade records for the given/current period from canvas
    # setting midterm to true clears midterm records and stores midterm records
    # start and merge sessions
    session = Session()
    course = session.merge(self)
    # get the current period if not given
    site = canvas_site()
    if not term:
      term = site.get_current_term()
    
    # clear out previous grade records for this period from the session/db
    session.query(Grade_Record).filter_by(course_id = course.sis_id).filter_by(term_id = term.term_id).delete()
    session.commit()
    # import the desired behavior for blanks:
    blanks_are_zero = strtobool(getenv('zero_blanks'))
    
    if blanks_are_zero:
        score='final_score'
        grade='final_grade'
    else:
        score='current_score'
        grade='current_grade'

    # API request to Canvas pulls grades for the period
    url=site.baseUrl +(
    f'courses/{course.canvas_id}/enrollments?'
    'per_page=80&type[]=StudentEnrollment'
    )
    api_response = requests.get(url, headers = site.header, timeout=120)
    api_response.raise_for_status()

    while len(api_response.json()):
        # This response is not nested
        for record in api_response.json():
          # check for pass/fail
          # many will be blank
          if not record['grades'][grade]:
            rec_grade = 'Pass'
            rec_score = None
          
          # some will have a grade
          elif record['grades'][grade] in ['Pass','pass','Fail','fail']:
            rec_grade = record['grades'][grade]
            rec_score = None
          
          # the rest (most)
          else:
            rec_grade = record['grades'][grade]
            rec_score = record['grades'][score]
          
          
          session.add(Grade_Record(student_id=record['user']['sis_user_id'],
                                      term_id=term.term_id,
                                      course_id=course.sis_id,
                                      score=rec_score,
                                      grade=rec_grade,
                                      quality_points=Grade_Record.get_quality_points(record['grades'][grade]),
                                      midterm = False))
          session.commit()
        # go to the next link if there is one; break if there isn't or it's empty
        # should not be needed
        if api_response.links.get('next',0):
            api_response = requests.get(api_response.links['next']['url'], headers=site.header, timeout=60)
        else:
            break
class Grade_Record(Base):
  __tablename__ = 'grade_records'

  # I'm going to make the ForeignKeys point to the string sis_id's so that we can more
  # easily add in historical data
  grade_record_id = Column(Integer, Sequence(
    'grade_record_id_sequence'), primary_key=True)
  student_id = Column(Unicode, ForeignKey('students.sis_id',onupdate="CASCADE", ondelete="CASCADE"))
  period_id = Column(Integer, ForeignKey('grading_periods.period_id'))
  term_id = Column(Integer, ForeignKey('terms.term_id'))
  course_id = Column(Unicode, ForeignKey('courses.sis_id',onupdate="CASCADE", ondelete="CASCADE"))
  score = Column(Numeric)
  grade = Column(Unicode)
  comment = Column(Unicode)
  quality_points = Column(Numeric)
  midterm = Column(Boolean, default = False)

  student = relationship("Student", back_populates="grade_records")
  grading_period = relationship(
    "Grading_Period", back_populates="grade_records")
  term = relationship("Term", back_populates="grade_records")
  course = relationship("Course", back_populates="grade_records")

  @staticmethod
  def get_quality_points(grade):
    # Takes a letter grade string and returns the quality points
    quality_points = None
    if grade=='A':
      quality_points = 4.0
    elif grade=='B+':
      quality_points = 3.5
    elif grade=='B':
      quality_points = 3.0
    elif grade=='C+':
      quality_points = 2.5
    elif grade=='C':
      quality_points = 2.0
    elif grade=='D':
      quality_points = 1.0
    elif grade=='F':
      quality_points = 0.0 
    
    return quality_points

class Attendance(Base):
  __tablename__ = "attendance"

  student_id = Column(Unicode, ForeignKey(
    'students.sis_id'), primary_key=True)
  period_id = Column(Integer, ForeignKey(
    'grading_periods.period_id'), primary_key=True)
  absences = Column(Numeric)
  tardies = Column(Integer)

  student = relationship("Student", back_populates="attendance_records")
  grading_period = relationship(
    "Grading_Period", back_populates="attendance")

class CRM_Field(Base):
  __tablename__ = "crm_fields"

  id = Column(Integer, primary_key=True)
  name = Column(Unicode)
  label = Column(Unicode, unique=True)
  column_name = Column(Unicode)

class Grading_Standard(Base):  
  __tablename__ = 'grading_standards'
  standard_id = Column(Integer, primary_key=True)
  standard_title = Column(Unicode)
  grading_scheme = Column(MutableDict.as_mutable(JSON)) #Dictionary List of names and values

  courses = relationship('Course', back_populates='grading_standard')

class Account(Base):
  __tablename__ = 'accounts'
  canvas_id = Column(Integer, primary_key=True)
  sis_id = Column(Unicode,unique=True)
  account_name = Column(Unicode)
  parent_account_id = Column(Integer, ForeignKey('accounts.canvas_id')) #Can be null if account is root
  root_account_id = Column(Integer, ForeignKey('accounts.canvas_id')) #or null if root account

  children = relationship('Account',foreign_keys=parent_account_id,
        backref=backref('parent',remote_side=[canvas_id]))
  courses = relationship('Course', back_populates='account')
 


# now that we've got all of the DB stuff created, we should actually make sure the DB gets created
# this can probably go away once we get an actual DB
Base.metadata.create_all(engine)


class canvas_site:
  
  # class for each canvas site so we can switch between test/staging/production
  # using multiple config.json files.
  # the constructor takes a file name for the .json configuration based on the Gerald Q Maguire conf
  # if no conf file is specified, it will attempt to load the info from config.json
  def __init__(self, host = None, api_key = None):
      if not api_key:
        api_key = getenv('canvas_access_token')
      if not host:
        host = getenv('canvas_host')
      
      self.header = {'Authorization': f'Bearer {api_key}'}
      self.baseUrl = f'https://{host}/api/v1/'
  
  def update_grading_standards(self):
    # Populates all of the grading standards in the DB with grading_standards from Canvas
    url = self.baseUrl + f'accounts/{getenv("root_account")}/grading_standards'
    api_response = requests.get(url, headers=self.header, timeout=60)
    api_response.raise_for_status() #exception if API call fails
    session = Session() #instantiate DB session

    while len(api_response.json()):
      for standard in api_response.json():
        
        # we only care about Account standards
        if standard['context_type'] == 'Account':
          session.merge(Grading_Standard(
            standard_id=standard['id'],
            standard_title=standard['title'],
            grading_scheme = {k:v for d in standard['grading_scheme'] for k,v in d.items()}))
          session.commit()

      # go to the next link if there is one; break if there isn't or it's empty
      # should never be more than a single page
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=self.header, timeout=60)
      else:
        break
    session.commit()
  
  def update_accounts(self):
    #Populates all accounts, including subaccounts, in DB from Canvas
    #for account_no in range(1, int(getenv("no_accounts"))):
    url = self.baseUrl + f'accounts/{getenv("root_account")}/sub_accounts' #Reference root account number from env file. Use recursion to return all subaccounts
    params = {'recursive':True,
              'per_page':80} 
    # If recursive true, the entire account tree underneath this account will be returned (though still paginated). 
    # If false, only direct sub-accounts of this account will be returned. Defaults to false.
    api_response = requests.get(url, params=params, headers=self.header, timeout=60)
    api_response.raise_for_status() #exception if API call fails
    session = Session() #instantiate DB session

    while len(api_response.json()):
      for account in api_response.json():
        try:
          session.merge(Account(
            canvas_id=account["id"],
            sis_id=account['sis_account_id'], 
            account_name=account['name'], 
            parent_account_id=account['parent_account_id'],
            root_account_id = account['root_account_id'],
            ))
          session.commit()
        except Exception as e:
          print(e)

      # go to the next link if there is one; break if there isn't or it's empty
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=self.header, timeout=60)
      else:
        break

  def create_term(self,term_name,*,
              term_start_date = None, term_end_date = None,
              teacher_start_date = None, teacher_end_date = None,
              student_start_date = None, student_end_date = None):
    # Check whether term exists in Canvas and db. If new, create in Canvas and db.
    # start by making sure all terms from Canvas up-to-date in local db
    self.update_terms()

    session = Session()
    term = session.query(Term).filter_by(term_name = term_name).one_or_none()
    # this will fail if there exists more than one term with the same name
    
    if term:
      print(f'Error: term already exists with id {term.term_id}')
      return term
    
    # short-names make things more complex than necessary

    # date formatting: 
    # datetime.strptime(f'{term[0]+term[1]+term[2]+term[3]}-08-15 01:02:03', '%Y-%m-%d %H:%M:%S')
    # api docs say it accepts iso 8601, so let's not parse that out manually if we can avoid it
    
    # default values are 30 days in the future and 365 days in the future
    default_start = datetime.now() + timedelta(30)
    default_end = datetime.now() + timedelta(365)
    if not term_start_date:
      term_start_date = default_start.isoformat()
    if not term_end_date:
      term_end_date = default_end.isoformat()

    # we shouldn't make any assumptions about the given term name
    params = {'enrollment_term[name]':term,
      'enrollment_term[start_at]':term_start_date, #2015-01-10T18:48:00Z], #YMD
      'enrollment_term[end_at]':term_end_date
      } 
    # only pass in optional parameters if specified
    if teacher_start_date:
      params['enrollment_term[overrides][TeacherEnrollment][start_at]'] = teacher_start_date
    if teacher_end_date:
      params['enrollment_term[overrides][TeacherEnrollment][end_at]'] = teacher_end_date
    if student_start_date:
      params['enrollment_term[overrides][StudentEnrollment][start_at]'] = student_start_date
    if student_end_date:
      params['enrollment_term[overrides][StudentEnrollment][end_at]'] = student_end_date
     
    url = self.baseUrl + f'accounts/1/terms'
    api_response = requests.post(url, headers=self.header, params=params, timeout=60) #want "200" response to return course
    try: #Try except allows program to continue if exception thrown
      api_response.raise_for_status() #Anything but 200 throws exception
    except Exception as e:
      print(e)

    self.update_terms() #Add new term created to DB        

  def create_course(self, sis_id, full_name, account_id, *, print_name = None, term = None, grading_standard_id = None, default_view = None):
    
    # set defaults
    if not term:
      term = self.get_current_term()
    if not print_name:
      print_name = full_name
    
    params = {'course[name]':full_name,
              'course[course_code]':print_name,
              'course[term_id]':term.term_id,
              'course[sis_course_id]':sis_id
              }

    if default_view:
      params['course[default_view]'] = default_view 
      #shows recent activity feed as home page: feed, wiki, modules, syllabus, assignments
    
    if grading_standard_id:
      params['course[grading_standard_id]'] = grading_standard_id
            
    # add to canvas
    url = self.baseUrl + f'accounts/{account_id}/courses'
    print(f'url generated is {url}. \n')
    #Requests module handles the processing
    api_response = requests.post(url, headers=self.header, params=params, timeout=60) 
    try: 
      api_response.raise_for_status()
      print(f'{sis_id} created in Canvas.') 
    except Exception as e:
      print(e)
      print(f'{sis_id} failed to create in Canvas')
      return False

    # add to local db
    session = Session()
    course = api_response.json()
    try:
      crs = session.merge(Course(canvas_id=course['id'],
              sis_id=course['sis_course_id'],
              term_id=course['enrollment_term_id'],
              full_name=course['name'],
              print_name=course['course_code'],
              account_id=course['account']['sis_account_id']))
      session.commit()
      # set the homeroom flag
      crs.set_homeroom_guess()
      print(f'{sis_id} created in local DB.')
      return crs
    except Exception as e:
      print(e)
      print(f'{sis_id} failed to create in local DB')
    

  def update_terms(self):
    # Populates all of the terms in the DB with terms from Canvas
    # this leaves any orphan terms alone in case they come from a different source?
    url = self.baseUrl + f'accounts/{getenv("root_account")}/terms?per_page=80'
    api_response = requests.get(url, headers=self.header, timeout=60)
    api_response.raise_for_status()  # exception if api call fails
    session = Session()
    while len(api_response.json()):

      # I don't quite understand why the response is nested within 'enrollment_terms', but it is
      for term in api_response.json()['enrollment_terms']:
        if not term['grading_period_group_id']:
          print(f'No grading periods present for {term["name"]}')
          # continue # can't add term without linking to periods
        session.merge(Term(
          term_id=term['id'], term_name=term['name'], gp_group_id=term['grading_period_group_id']))
        session.merge(GP_Group(
          gp_group_id=term['grading_period_group_id'], gp_group_name=term['name']))

      # go to the next link if there is one; break if there isn't or it's empty
      # should never be more than a single page
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=self.header, timeout=60)
      else:
        break
    session.commit()

  def update_grading_periods(self):
    # Populates and links the grading_periods associated with a term in Canvas
    # Leaves orphans unchanged
    url = self.baseUrl + f'accounts/{getenv("root_account")}/grading_periods?per_page=80'
    api_response = requests.get(url, headers=self.header, timeout=60)
    api_response.raise_for_status()  # exception if api call fails
    session = Session()
    while len(api_response.json()):

      # I don't quite understand why the response is nested within 'grading_periods', but it is
      # without specifying it, the iteration only includes it as the one iteration
      for period in api_response.json()['grading_periods']:
        session.merge(Grading_Period(
          period_id=period['id'], period_name=period['title'], gp_group_id=period['grading_period_group_id']))
        # I'm not going to update GP Groups here because if a gp group isn't assigned to a term, it can't be assigned to a class

      # go to the next link if there is one; break if there isn't or it's empty
      # should never be more than a single page
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=self.header, timeout=60)
      else:
        break
    session.commit()
    return  
    
  def get_current_term(self):
    session = Session()
    term = session.query(Term).filter_by(term_name=getenv("current_term_name")).one_or_none()
    if not term:
      # pull terms from canvas if the current term can't be found
      self.update_terms()
      self.update_grading_periods() # these are necessary for fully functional terms
      # session.expire_all() # this may be necessary to relaod the updated terms from the db
      term = session.query(Term).filter_by(term_name=getenv("current_term_name")).one_or_none()
      if not term: # if still can't find it print error
        print('Unable to find current term: please check your .env file for a current_term_name that matches a term in Canvas')
        return None
    return term
  def get_current_period(self):
    term = self.get_current_term()
    for grading_period in term.gp_group.grading_periods:
      # return the first period that matches within the current term
      if grading_period.period_name == getenv("current_period_name"):
        return grading_period
    # if none match, print error and return None?
    print('Unable to find current grading period: please check your .env file for a current_period_name that matches a period within the current term in Canvas')
    return None

  def get_cumulative_periods(self,*, period = None):
    # returns all of the periods for the term up to the current period
    session = Session()

    # default to current period
    if not period:
      period = self.get_current_period()

    period = session.merge(period)
    
    # start with empty list to build up periods
    periods = []

    for p in session.query(Grading_Period) \
          .filter_by(gp_group_id = period.gp_group_id):
        
      if p.period_id <= period.period_id: # this will have to do until I store dates for grading periods
        periods.append(p)

    periods.sort(key = lambda period: period.period_id)

    return periods
  
  def export_student_accounts(self,*,filename = None, id_limit = 's1',grade_min = -1,grade_max = 12):
    # exports student info needed to update google accounts:
    # name, email, password?, parent email, parent phone?, grad year?, last login?
    session = Session()
    # check/set filename
    if not filename:
      filename = f'generated_docs/student_accounts_export.xlsx'
    else:
      if 'generated_docs' not in filename:
        filename = f'generated_docs/{filename}'
      if filename[-5:] != '.xlsx':
        filename = f'{filename}.xlsx'
    
    # generate passwords for students if they haven't yet been set
    students = session.query(Student).filter_by(active=True).filter(Student.password.is_(None)).all()
    for student in students:
      student.password = gen_password(8)
    session.commit()

    # get dataframe to write to xlsx
    df = pandas.read_sql(
      session.query(
        Student.sis_id.label('student_id'), 
        Student.common_name.label('First Name [Required]'),
        Student.last_name.label('Last Name [Required]'),
        Student.email.label('Email Address [Required]'),
        Student.password.label('Password [Required]'),
        literal_column("'/School CH-IN-SM/School Louisville/Students'").label('Org Unit Path [Required]'),
        (Student.graduation_year - 2000).label('Department'), # just the last digits
        Parent.email.label('Recovery Email'),
        ('+1'+Parent.phone).label('Recovery Phone [MUST BE IN THE E.164 FORMAT]'))
        .join(Student.parents)
        .filter(Student.sis_id.startswith(id_limit))
        .filter(Student.grade >= grade_min)
        .filter(Student.grade <= grade_max)
        .filter(Student.active == True).statement, 
        session.bind)
    df.to_excel(filename,f'students')
  
  def export_students(self,*,filename = None,id_limit = None,grade_min = -1,grade_max = 12):
    # exports student email data for the students in the given term
    session = Session()
    if not id_limit:
      id_limit = 's1'

    if not filename:
      filename = f'current_students.xlsx'

    # put the file in generated_docs
    if 'generated_docs' not in filename:
      filename = 'generated_docs/'+filename
    # make sure filename ends in .xlsx
    if filename[-5:] != '.xlsx':
      filename = filename + '.xlsx'

    df = pandas.read_sql(
      session.query(
        Student.sis_id.label('student_id'), 
        Student.common_name,
        Student.last_name,
        Student.email,
        Student.password)
        .filter(Student.sis_id.startswith(id_limit))
        .filter(Student.grade >= grade_min)
        .filter(Student.grade <= grade_max)
        .filter(Student.active == True).statement, 
        session.bind)
    df.to_excel(filename,f'students')
  
  def pull_student_canvas_ids(self,*,id_limit='s10'):
    # Pulls all 'StudentEnrollment' users from Canvas to get canvas ID
    # this should only be necessary if students are manually added to canvas without first being in CRM or if something breaks in the import
    # let's consider removing this
    # n.b. Canvas documentation gives the wrong names for enrollment_types
    session = Session()  

    # also use 'search_term':id_limit to narrow the list, but you can't specify where to search. Search also requires 3 char min.
    params = {'enrollment_type':'student',
              'per_page':80}
    if len(id_limit) >= 3:
      params['search_term'] = id_limit
    
    url = self.baseUrl + f'accounts/{getenv("root_account")}/users'
    api_response = requests.get(url, headers=self.header, params=params, timeout=60)
    api_response.raise_for_status()  # exception if api call fails
    while len(api_response.json()):

      # This response is not nested
      for user in api_response.json():
        if not user.get('sis_user_id'):
          # if there is not sis_id, continue to next user
          print(f'Unable to create entry for {user["name"]}: they seem to be missing an SIS ID')
          # consider removing this enrollment/user instead of skipping?
          continue

        # skip students without matching id's
        if not id_limit in user['sis_user_id']: # lazy way to check -could probably be much faster
          continue

        # get students
        try:
          # get student with matching canvas id:
          # if there isn't one, create/update
          # if sis_id matches, update
          # if the sis_id doesn't match, delete the canvas_id and create/update based on sis
          student_c = session.query(Student).filter_by(canvas_id=user['id']).one_or_none()
          sortable_name = user['sortable_name'].split(', ')
          if not student_c:
            session.merge(Student(sis_id=user['sis_user_id'], canvas_id=user['id'],common_name=sortable_name[1], last_name=sortable_name[0]))
            session.commit()
          elif not student_c.sis_id == user['sis_user_id']:
            student_c.canvas_id = None
            session.merge(student_c)
            session.merge(Student(sis_id=user['sis_user_id'], canvas_id=user['id'],common_name=sortable_name[1], last_name=sortable_name[0]))
            session.commit()

        except:
          print(f'Error with student {user["name"]}')
          traceback.print_exc()
          session.rollback()
          continue
        
      # go to the next link if there is one; break if there isn't or it's empty
      # should have multiple pages--too many for a 'last' link
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=self.header, timeout=60)
      else:
        break
  
  def update_teachers(self):
    # Pulls all 'TeacherEnrollment' users from Canvas
    # n.b. Canvas documentation gives the wrong names for enrollment_types
    # this ignores any old or orphan teachers
    session = Session()      
    for teacher in session.query(Teacher).all():
      teacher.active = False

    url = self.baseUrl + f'accounts/{getenv("root_account")}/users?enrollment_type=teacher&per_page=80'
    api_response = requests.get(url, headers=self.header, timeout=60)
    api_response.raise_for_status()  # exception if api call fails
    while len(api_response.json()):

      # This response is not nested
      for user in api_response.json():
        if not user.get('sis_user_id'):
          # if there is not sis_id, continue to next user
          print(f'Unable to create entry for {user["name"]}: they seem to be missing an SIS ID')
          continue

        # get teachers
        try:
          session.merge(Teacher(sis_id=user['sis_user_id'], canvas_id=user['id'],
                      teacher_name=user['name'], active=True))
          session.commit()
        except:
          print(f'Error with teacher {user["name"]}')
          continue
        
      # go to the next link if there is one; break if there isn't or it's empty
      # should have multiple pages--too many for a 'last' link
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=self.header, timeout=60)
      else:
        break
    
  def update_courses(self, *, term = None):
    # Pulls courses from canvas in the given/current term
    # excludes courses without any enrollments
    if not term:
      term = self.get_current_term()
    url = self.baseUrl + \
      f'accounts/{getenv("root_account")}/courses?include[]=account&with_enrollments=true&enrollment_term_id={term.term_id}&per_page=80'
    # pulls 80 responses at a time instead of default 10
    api_response = requests.get(url, headers=self.header, timeout=60)
    api_response.raise_for_status()  # exception if api call fails
    session = Session()
    while len(api_response.json()):

      # This response is not nested
      for course in api_response.json():
        # courses added via the web ui must have sis_id added or they will be skipped
        if not course.get('sis_course_id'):
          print(f'Unable to add {course["name"]}: it appears to be missing an SIS ID')
          continue

        try:
          sis_account_id = course['account']['sis_account_id']
        except Exception as e:
          print(e)
          sis_account_id = None
          print(
            f'Could not get sis_account_id for course {course["name"]} {course["id"]}')
        crs = session.query(Course).filter_by(canvas_id=course['id']).one_or_none()
        if not crs:
          crs = session.merge(Course(canvas_id=course['id'],
                    sis_id=course['sis_course_id'],
                    term_id=course['enrollment_term_id'],
                    full_name=course['name'],
                    print_name=course['course_code'],
                    account_id=sis_account_id))
        else:
          crs.sis_id=course['sis_course_id']
          crs.term_id=course['enrollment_term_id']
          crs.full_name=course['name']
          crs.print_name=course['course_code']
          crs.account_id=sis_account_id
        
        session.commit()
        # set the homeroom flag
        crs.set_homeroom_guess()

      # go to the next link if there is one; break if there isn't or it's empty
      # should have multiple pages, but probably still has a 'last' link
      if api_response.links.get('next', 0):
        api_response = requests.get(
          api_response.links['next']['url'], headers=self.header, timeout=60)
      else:
        break

  def update_students_grade(self):
    session = Session()
    for student in session.query(Student).filter_by(active = True).all():
      student.update_grade()

  # depreciated in favor of pulling student grades from CRM
  # should be removed once CS students can be pulled from CRM
  def guess_grades(self): # this is the wrong place for this function, but it's wrong anyway
    # fills in grades/grad_years for all students
    # student enrollment data and homerooms must already exist in the db
    session = Session()
    term = self.get_current_term()
    session.merge(term)
    # we can pull homerooms from the current term
    courses = session.query(Course).filter_by(term_id = term.term_id).filter_by(homeroom = True).all()
    for course in courses:
      if course.sis_id[6] == 'P':
        if course.sis_id[8] == 'K': # for JK - 2019SMPJK
            grade = -1
        else:
            grade = int(course.sis_id[8]) # this works as the only primary courses should have 0, 1, or 2
      else:
        grade = int(course.sis_id[7:9])

      for section in course.sections:
          for student in section.students:
            student.grade = grade
            session.merge(student)
            session.commit()

  def set_student_pw(self,user,*,password = None):
    # sets new username, password, and/or sis_id for the given canvas user
    # looks for a login to update and then does
    # creates a new login if not found
    # returns the password if successful
    session = Session()
    # generate pw if none:
    if not password:
      password = gen_password(10)
    
    # load the params with the new password etc
    params = {'login[password]':password}

    # fire up the session

    # set url to get logins for user
    url = self.baseUrl + f'users/{user.canvas_id}/logins'
  
    # get all logins for the user id
    for login in requests.get(url,headers=self.header, timeout=60).json():
      # might be more than one someday?
      if login.get('unique_id',0)==user.sis_id:
        # we found the login for the user using their sis_id!
        # use the login id we found
        url = self.baseUrl + f'accounts/{getenv("root_account")}/logins/{login["id"]}'
        api_response = requests.put(url, headers=self.header, params=params, timeout=60)
        try:
          api_response.raise_for_status()  # exception if api call fails
          user.password = password
          session.merge(user)
          session.commit()
          return True
        except:
          break
    
    # let's try the create function if we haven't found a login with sis_id
    params = {'user[id]':user.canvas_id,
              'login[unique_id]':user.sis_id,
              'login[password]':password,
              'login[sis_user_id]':user.sis_id}
    url = self.baseUrl + f'accounts/{getenv("root_account")}/logins'
    api_response = requests.post(url, headers=self.header, params=params, timeout=60)
    try:
      api_response.raise_for_status()  # exception if api call fails
      user.password = password
      session.merge(user)
      session.commit()
      return True
    except:
      return False

  def set_student_login(self,user,*, provider = None):
    # sets new username, password, and/or sis_id for the given canvas user
    # looks for a login to update and then does
    # creates a new login if not found
    session = Session()

    if not provider:
      provider = 'google'

    # load the params with the new stuff as needed etc
    params = {'login[authentication_provider_id]':provider,
              'login[unique_id]':user.email}


    # Check first if the user already exists:
    # set url to get logins for user
    url = self.baseUrl + f'users/{user.canvas_id}/logins'
  
    # get all logins for the user id
    for login in requests.get(url,headers=self.header, timeout=60).json():
      # see if we have a login with the email School yet
      if login.get('unique_id',0) == user.email: #already has email
        print(f'Student {user.sis_id} is already using email {user.email}')
        return False
      elif '@students.example.com' in login.get('unique_id',0): # has wrong School emal
        # use the login id we found and change the email
        url = self.baseUrl + f'accounts/{getenv("root_account")}/logins/{login["id"]}'
        api_response = requests.put(url, headers=self.header, params=params, timeout=60)
        try:
          api_response.raise_for_status()  # exception if api call fails
          print(f'Student {user.sis_id} email has been updated to {user.email}')
          return True
        except:
          break

    print(f'Student {user.sis_id} has not email- attempting to create . . .')
    # let's try the create function?
    params = {'user[id]':user.canvas_id,
              'login[unique_id]':user.email,
              'login[authentication_provider_id]':provider}
    url = self.baseUrl + f'accounts/{getenv("root_account")}/logins'
    api_response = requests.post(url, headers=self.header, params=params, timeout=60)
    try:
      api_response.raise_for_status()  # exception if api call fails
      return True
    except Exception as e:
      print(e)
      return False
  
  def get_highest_id(self,*,starts_with = 's1',refresh = True):
    # get ordered list of ids from db, returns the one at the end

    # refresh local with canvas
    if refresh:
      # self.update_students(crm_lookup=False)
      print(f'Getting student ids from Canvas is not currently available')
    
    session = Session()
    students = session.query(Student).filter(Student.sis_id.startswith(starts_with)).order_by(Student.sis_id).all()

    return students[-1].sis_id

  def push_students(self,*,active = True,add_missing = False):
    # pushes student data from local DB to Canvas
    session = Session()
    if active:
      students = session.query(Student).filter_by(active = True).all()
    else:
      students = session.query(Student).all()
    
    for student in students:
      student.push_to_canvas(canvas = self,add_missing = add_missing)

class crm_site:
  # holds the keys, url, and data to be used for api requests
  # default init takes these from the .env file
  # could create class method to construct with other data source
  def __init__(self):
    api_key = getenv("crm_api_key")
    # ugly error notification in place of genuine error handling
    if not api_key:
      print("Unable to read api key from .env")
    
    site_key = getenv("crm_site_key")
    if not site_key:
      print("Unable to read site key from .env")
    
    host = getenv("crm_host")
    if not api_key:
      print("Unable to read host from .env")

    self.url = f'https://{host}/sites/all/modules/civicrm/extern/rest.php'
    
    # this is the only content-type I've gotten to work with CRM
    self.headers = {'Content-type': 'application/x-www-form-urlencoded'}
    
    self.data = {'api_key': api_key, 'key': site_key, 'version': '3'} 
  
  def pull_students(self):
    # get all current student info
    session = Session()
    # reset data that's about to be updated?
    l_students = session.query(Student).all()
    for ls in l_students:
      ls.active = False

    # query crm for Current Students
    search = {'School Status':'Current Student'}
    fields = ['School Status','Grad Year','First Name','Middle Name','Common Name','Last Name', 'Student ID','Birthday','House','Sex']
    students = self.get_child_fields(fields,search)    
    for family_id,fam_dat in students.items():
      for child_id,child_dat in fam_dat.items():
        # skip any non School children
        if 'Current Student' not in child_dat['School Status']:
          continue
        elif not child_dat['Student ID']:
          print(f'{child_dat["Common Name"]} {child_dat["Last Name"]} has no student ID in CRM - skipping')
          continue
        try:
          # get valid Birthday
          try:
            birthday = dateutil.parser.isoparse(child_dat['Birthday'])
          except:
            print(f'Student {child_dat["Student ID"]} invalid Birthday: {child_dat["Birthday"]}')
            birthday = None
          
          student = session.merge(Student(
              sis_id = child_dat['Student ID'],
              common_name = child_dat['Common Name'],
              first_name = child_dat['First Name'],
              middle_name = child_dat['Middle Name'],
              last_name = child_dat['Last Name'],
              birthday = birthday,
              gender = child_dat['Sex'],
              graduation_year = child_dat['Grad Year'],
              house = child_dat['House'],
              active = True
              ))
          session.commit()
          student.gen_email()
          
        except Exception as e:
          print(e)
          session.rollback()
          input("Press a key to continue")
    
    return
  
  def update_parents(self,*, active = True):
    # get parent info for all students
    session = Session()
    if active:
      students = session.query(Student).filter_by(active = True).all()
      parents = session.query(Parent).all()
      for parent in parents:
        parent.active = False
      for student in students:
        student.update_parents(site=self,active = active)
        # print(f'Added parents for {student.common_name} {student.last_name}')
    else:
      students = session.query(Student).all()
      for student in students:
        student.update_parents(site=self,active = False)
        # print(f'Added parents for {student.common_name} {student.last_name}')
      self.set_active_parents()


  def set_active_parents(self):
    # lookup all active parents in crm and set them active in the db?
    # get active parents
    active_parents = list(self.get_contacts_by_label('School Status','Current Student'))

    # start a session and parse through these parents
    session = Session()
    # get all parents
    parents = session.query(Parent).all()

    for parent in parents:
      if parent.crm_id in active_parents:
        parent.active = True
      else:
        parent.active = False
    session.commit()

  
  def api_get(self,*, json = None, entity = "Contact"):
    # api get requests; returns dict with the response
    # I don't actually want to update the self.data with the new junk-it may change in the future
    data = self.data.copy()
    data.update({"entity" : entity, "action" : "get","json" : json})
    data = self.convert_data(data)
    # for some reason CiviCRM seems to require a POST instead of a GET for this request . . .
    # It's possible I just have syntax wrong, but POST works and GET doesn't
    return requests.post(self.url,data=data, headers=self.headers).json()
  
  def api_set(self,*, json = None, entity = "Contact"):
    # api get requests; returns dict with the response
    # I don't actually want to update the self.data with the new junk-it may change in the future
    data = self.data.copy()

    data.update({"entity" : entity, "action" : "create","json" : json})
    data = self.convert_data(data)
    # for some reason CiviCRM seems to require a POST instead of a GET for this request . . .
    # It's possible I just have syntax wrong, but POST works and GET doesn't
    return requests.post(self.url,data=data, headers=self.headers).json()  
  
  def set_custom_field(self, family_id, field_label, child_id, value):
    # changes the value of a custom field for a contact
    # NB if the child_id field doesn't exist for the contact, a new one may be created
    # json = {'entity_id':2,'custom_3:1791':'Amunrud'} 
    json = {
      'entity_id':family_id,
      f'{self.get_api_field(field_label)}:{child_id}':value
    }
    return  self.api_set(json = json, entity = "CustomValue")

  def update_custom(self):
    # pulls custom item field info from site and writes to the DB
    # entity=CustomGroup&action=get&api_key=userkey&key=sitekey&json={"title":"Child Info","api.CustomField.get":{},"is_active":1}
   
    # it may not be safe to pull all of these at once, but that's what I'm aiming to do
    json = {"api.CustomField.get":{},
            "is_active":1,
            "sequential":1}
    response = self.api_get(json = json, entity = "CustomGroup")
    
    
    try:
      # clean out old cruft?
      # only if we get a valid-ish response
      if response['count'] > 0:
        session = Session()
        session.query(CRM_Field).delete()
        session.commit()
        for custom_group in response['values']:
          for record in custom_group['api.CustomField.get']['values']:
            session.merge(CRM_Field(id = record['id'], name = record['name'],label = record['label'], column_name = record['column_name']))
            session.commit()
    except:
      print('Oops')
    
  def get_highest_id(self,*,starts_with = 's1'):
    # get all student id's from crm
    id_nest_list = self.get_child_fields(['Student ID'],{'Student ID':{'>=':starts_with}}) #  {'IS NOT NULL':1}
    id_list = []
    for fam_dat in id_nest_list.values():
      for child_dat in fam_dat.values():
        if child_dat['Student ID'][0:len(starts_with)]==starts_with:
          id_list.append(child_dat['Student ID'])
    id_list.sort()

    return id_list[-1]

  
  def get_child_fields(self,field_list,search_dict = None):
    # queries crm using the search list 
    # returns a dict indexed by family_id, child_id, and field name
    # field list looks like ['School Status','Grad Year']
    # search list looks like {'School Status':'Reenrolled'} or like 'School Status':['Reenrolled','Current Student']
    # other tests are possible with {'School Status':'{'IS NULL':1}}
    # IMPORTANT the search is only valuable for the simplest searches or keeping results small - 
    # if one child matches the terms, all of them will be returned

    # translate search_dict into valid json with crm fields
    # start with unlimited search length
    json = {"options":{"limit":0}}
    
    # add in each search item
    for field,value in search_dict.items():
      json[self.get_api_field(field)] = value

    # add return list and options to the api chain
    chain_json = {'sequential':0}
    chain_json['return'] = [self.get_api_field(f) for f in field_list]

    # add chain to json
    json['api.CustomValue.get'] = chain_json

    # api call
    results =  self.api_get(json = json, entity = "Contact")

    # now package it all up
    return_dict = {}
    # iterate through each family; separate the id and data
    for family_id,fam_dat in results['values'].items():
      return_dict[family_id] = {}
    
      # iterate through each returned field
      for field_id,field_dat in fam_dat['api.CustomValue.get']['values'].items():
        
        # remove junk fields
        junk = ['entity_id','entity_table','latest','id']
        for key in junk:
           del field_dat[key]
        
        # go through data and add it to return_dict
        for child_id,field_value in field_dat.items():
          # if the return_dict doesn't already have entries for the child, we need to add it
          if child_id not in return_dict[family_id]:
            return_dict[family_id][child_id] = {}

          return_dict[family_id][child_id][self.get_field_label(field_id)] = field_value

    return return_dict


  def get_contacts_by_label(self,field_label,search_value):
    # performs a crm search using data from a custom field ("Child Info")
    # takes the field name as it appears on CRM as an input
    # looks up that name in the DB and searches for the given value

    session = Session()
    field_id = session.query(CRM_Field).filter_by(label = field_label).one().id
    # to get contact filtered by custom data use custom+_<the id of the custom field>
    # for School student id, that evaluates to custom_73
    
    json = {f'custom_{field_id}':search_value,"options":{"limit":0}}

    return self.api_get(json = json, entity = "Contact")['values']

  
  def get_child_field(self,family_id,child_id,field_label):
    # returns the value for the given family, child, and field
    field = self.get_api_field(field_label)
    json = {'entity_id':family_id,
            'sequential':1,
            'return':field
          }
    results =  self.api_get(json = json, entity = "CustomValue")
    # Values should be nested in a single item list
    return results['values'][0][f'{child_id}']
  
  def get_field_by_field(self,search_field_label,search_value,return_field_label):
    # returns a list of field values by searching for a field value: ie return a list of student ID's for students where House = George
    # if the field is empty in CRM, it will include a blank entry in the return list
    return_field = self.get_api_field(return_field_label)

    # remove the limit by adding in limit:0 option
    json = {"return":return_field,
            self.get_api_field(search_field_label):search_value,
            "options":{"limit":0}
            }

    results =  self.api_get(json = json, entity = "Contact")['values']

    #iterate through the values in the dict to create a list to return
    return_list = []
    try:
      for result in results.values():
        return_list.append(result[return_field])
    except:
      print(f'Error searching for {search_field_label}.  CRM returned {results} when searching for {search_value}')
      return_list = ['']

    return return_list
  
  def get_ids_to_change(self,search_field_label,search_value):
    session = Session()
    search_field_id = session.query(CRM_Field).filter_by(label = search_field_label).one().id
    # to get contact filtered by custom data use custom+_<the id of the custom field>
    # for School student id, that evaluates to custom_73
    
    #json = {"return":f'custom_{return_field_id}',f'custom_{search_field_id}':search_value}
    # remove the limit by adding in limit:0 option
    json = {"return":f'id',f'custom_{search_field_id}':search_value,"options":{"limit":0}}

    return  self.api_get(json = json, entity = "Contact")['values']

    
  @staticmethod
  def get_api_field(field_label):
    # looks up the custom_3 style filed label for api calls from the label that appears on the website
    session = Session()
    try:
      field_id = session.query(CRM_Field).filter_by(label = field_label).one().id
      return f'custom_{field_id}'
    except Exception as e:
      print(e)
      print(f'Problem with {field_label}')
    
    
  
  @staticmethod
  def get_field_label(api_id):
    # looks up the label for crm field based on the id
    session = Session()
    return session.query(CRM_Field).filter_by(id = api_id).one().label
  
  @staticmethod
  def convert_data(data):
    # I'm using a static method for namespacing as well as to avoid inadvertently modifying a class instance
    # passing a nested dict into the request data option mangles the json section
    # civicrm requires for sequential queries
    # processing with liburl works, but then additionally requires that 
    # content-type headers must be explicitly set to "application/x-www-form-urlencoded"
    # convert json's nested dict to str
    return urlencode(data).replace('%27','%22')


def gen_password(length):
  alphabet = string.ascii_letters + string.digits + '!@#$%^&*'
  ambig_chars = ['I','1','l','0','O']
  alphabet = ''.join(ch for ch in alphabet if ch not in ambig_chars)
  
  while True:
    password = ''.join(secrets.choice(alphabet) for i in range(length))
    if any(c.isdigit() for c in password):
      break
  return password

