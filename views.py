# Module: views.py
# classes for generating reports and other grade system output

# give everything a pyhtml method?


import pdfkit  # generate pdfs from html
import pyhtml  # handle html tags, etc
import datetime  # handle dates
import os # managing files and directories
import pandas # fun data manipulation and import/export
from time import ctime  # for keeping track of times
from decimal import Decimal, localcontext, ROUND_DOWN  # use to truncate grades predictably
from model import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, canvas_site, Session, crm_site
from sqlalchemy import func, literal, cast, Integer, Unicode


def itbs_export(filename = None, id_limit = 's1', grade_min = 0,grade_max = 8):
  # exports list of students for barcode label order
  session = Session()
  term = canvas_site().get_current_term()
  
  if not filename:
      filename = f'ITBS_{term.term_name}.xlsx'
  
  # Last Name
  # First Name
  # Middle Name ? (blank)
  # Date of Birth
  # Gender
  # Grade
  # School / Building Name (Campus)
  # School / Building Code (Blank)
  # Class Name (Homeroom Teacher name)
  # Class Code (blank)
  # Student ID Number (int of last 5 digits of sis_id)
  # Additional ID Number (blank)
  # ITBS or ITED or Logramos Form (G)
  # ITBS or ITED or Logramos Level (Grade + 6)

  df = pandas.read_sql(
      session.query( 
        Student.last_name.label('Last Name'),
        Student.first_name.label('First Name'),
        literal('').label('Middle Name'),
        # Student.birthday.label('Date of Birth'), # this would be too easy
        (func.substr(cast(Student.birthday,Unicode),6,2)
          +'/'
          +func.substr(cast(Student.birthday,Unicode),9,2)
          +'/'
          +func.substr(cast(Student.birthday,Unicode),1,4)
          ).label('Date of Birth'),
        Student.gender.label('Gender'),
        Student.grade.label('Grade'),
        func.substr(Section.section_name,1,2).label('School / Building Name'),
        literal('').label('School / Building Code'),
        Teacher.teacher_name.label('Class Name'),
        func.substr(Section.section_name,1,5).label('Class Code'),
        func.substr(Student.sis_id,4,5).cast(Integer).label('Student ID Number'),
        literal('G').label('ITBS or ITED or Logramos Form'),
        (Student.grade+6).label('ITBS or ITED or Logramos Level'))
        .join(Term.courses)
        .join(Course.sections)
        .join(Section.students)
        .join(Course.teachers)
        .filter(Course.term_id == term.term_id)
        .filter(Student.sis_id.startswith(id_limit))
        .filter(Student.grade >= grade_min)
        .filter(Student.grade <= grade_max)
        .filter(Student.active == True)
        .filter(Course.homeroom == True).statement, 
        session.bind)
  df.to_excel(filename,f'{term.term_name}')


  
def rebuild_html(file = None):
  canv = canvas_site()
  if not file:
    file = f'generated_docs/{canv.get_current_term().term_name}/{canv.get_current_period().period_name}'
  
  hname = f'{file}.html'
  pname = f'{file}.pdf'
  options = {
              'enable-local-file-access': None,
              'page-size': 'letter',
              'orientation': 'portrait',
              'margin-top': '2cm',
              'margin-right': '2cm',
              'margin-bottom': '1cm',
              'margin-left': '2cm',
              'encoding': "UTF-8",
              'disable-smart-shrinking':'',
              'custom-header' : [
                ('Accept-Encoding', 'gzip')
                ]
              }
  pdfkit.from_file(hname, pname, options=options)

def cs_individual_reports(final = False):
  # creates individual pdf for each active cs student
  session = Session()
  s = session.query(Student).filter(Student.sis_id.startswith('C'))\
                            .filter_by(active = True).all()
  p = canvas_site().get_current_period()

  for student in s:
    rc=cs_report_card(student,p,final = final)
    rc.pdf()

def School_individual_reports(final = False):
  # creates individual pdf for each active School student
  session = Session()
  s = session.query(Student).filter(Student.sis_id.startswith('s1'))\
                            .filter_by(active = True)\
                            .filter(Student.grade >= 3)\
                            .filter(Student.grade <= 12).all()
  p = canvas_site().get_current_period()

  for student in s:
    if student.grade <= 6:
      rc=ls_report_card(student,p,final = final)
    else:
      rc=us_report_card(student,p, final = final)
    rc.pdf()

def trimester_report_cards(final = False):
  session = Session()

  students = session.query(Student)\
                .filter_by(active = True)\
                .filter(Student.sis_id.startswith('s1'))\
                .filter(Student.grade >= 3)\
                .filter(Student.grade <= 12)\
                .order_by(Student.last_name).all()
  period = canvas_site().get_current_period()
  
  # Start with empty report batch
  batch = report_batch(css='progressreport.css', title ='School Trimester Report Cards')
  
  # add report for each student
  for student in students:
    # catch LS
    if student.grade < 7:
      batch.add_report(ls_report_card(student,period, final = final).pyhtml())
    else:
      batch.add_report(us_report_card(student,period, final = final).pyhtml())
  
  # output
  batch.pdf()


def cs_report_cards(final = False):
  session = Session()

  students = session.query(Student)\
                .filter(Student.sis_id.startswith('C'))\
                .order_by(Student.last_name).all()
  period = canvas_site().get_current_period()
  
  # Start with empty report batch
  batch = report_batch(css='progressreport.css',title = 'CS Report Cards')
  
  # add report for each student
  for student in students:
    batch.add_report(cs_report_card(student,period, final = final).pyhtml())
  
  # output
  batch.pdf(name = "CS_Report_Cards")
class grade_rec: # grade record for inclusion on a report
  # base class grade reports
  # must have student, course, period(s)
  def __init__(self,student,course,*,period = None, final = False, midterm = False):
    # if period is given, update the class variable
    if period:
      self.set_periods(period)
    self.set_student(student)
    self.set_course(course)
    # self.periods = grade_rec.periods
    self.set_records(final = final,midterm = midterm)
  
  # NB: I don't know if I am doing this right. It will work for the simple one report at a time method
  # quite what will happen when this is part of a larger program, I'm uncertain
  # I'm also unsure quite how this works with inheritance
  @classmethod
  def set_periods(cls,period,*,cumulative = True):
    # sets list of periods for all grade_rec instances
    cls.periods = []
    if not cumulative:
      cls.periods = [period]
    else:
      cls.periods = canvas_site().get_cumulative_periods(period = period)

  def set_student(self,student):
    self.student = student

  def set_course(self,course):
    self.course = course

  def set_records(self,*,final = False, midterm = False):
    # Go through each period (term if final) and grab letter, %'s, and comments for the course/student
    # create a nested dict with gp_name as first key
    # grade, score, comment are nested keys
    session = Session()
    student = session.merge(self.student)
    course = session.merge(self.course)
    self.records = {}
    
    for period in self.periods:
      rec = session.query(Grade_Record).filter_by(student_id = student.sis_id) \
        .filter_by(period_id = period.period_id) \
        .filter_by(course_id = course.sis_id) \
        .filter_by(midterm = midterm).one_or_none()
      if not rec:
        self.records[period.period_id]={'grade':None,'score':None,'comment':None}
      else:
        self.records[period.period_id]={'grade':rec.grade,'score':rec.score,'comment':rec.comment}
    if final:
      rec = session.query(Grade_Record).filter_by(student_id = student.sis_id) \
        .filter_by(term_id = period.get_term().term_id) \
        .filter_by(course_id = course.sis_id) \
        .one_or_none()
      if not rec:
        self.records['final']={'grade':None,'score':None}
      else:
        self.records['final']={'grade':rec.grade,'score':rec.score}
    
  def course_name(self):
    # I may need to fire up a session to pull this data
    return self.course.print_name
  
  def teacher_name(self):
    # join together the list of teacher names
    session = Session()
    course = session.merge(self.course)
    try:
      teachers = []
      for i in range(len(course.teachers)):
        teachers.append(pyhtml.p(course.teachers[i].teacher_name))
      return teachers
    except Exception as e:
      print(e)
      print(course.sis_id)
      return None
  def comment(self):
    # comment comes from the last period in the periods list
    return self.grade_recs[self.periods[-1].period_id['comment']]
    
class us_grade_rec(grade_rec):
  # why do I need this? fun?
  def __init__(self,student,course,**kwargs):
    grade_rec.__init__(self,student,course,**kwargs)

class ls_grade_rec(grade_rec):

  # dict for course renaming and reordering
  # print name, order, part of composite course
  course_rename = {'Math':['Arithmetic',1,False],
                   'Latin':['Latin',2,False],
                   'Literature':['Literature',3,False],
                   'Language Arts':['Language Arts',4,False],
                   'Spelling':['Spelling',5,True],
                   'Penmanship':['Penmanship',6,True],
                   'Grammar':['Grammar',7,True],
                   'Composition':['Composition',8,True],
                   'Geography':['Geography',9,False],
                   'American Studies':['American Studies',10,False],
                   'Classical Studies':['Classical Studies',11,False],
                   'Christian Studies':['Christian Studies',12,False],
                   'Science':['Science',13,False],
                   'Art':['Art',14,False],
                   'Choir':['Choir',15,False],
                   'Music':['Music',16,False],
                   'Physical Education':['PE',17,False]}

  def __init__(self,student,course,**kwargs):
    grade_rec.__init__(self,student,course,**kwargs)

    # set the order and rename things
    # need a session to grab teacher info:
    session = Session()
    course = session.merge(self.course)

    # LS reports don't use teacher for most courses, but if there is a teacher different from the homeroom teach,
    # teach should be added to the course name
    
    # Start with given name
    self.course_name = self.course.print_name

    # rename according to dict and set order
    rename_dat = self.course_rename.get(self.course_name,False)
    if rename_dat:
      self.course_name = rename_dat[0]
      self.order = rename_dat[1]
      self.composition = rename_dat[2]
    else:
      found_course = False
      for cname,cdat in self.course_rename.items():
        if cname in self.course_name:
          self.course_name = cdat[0]
          self.order = cdat[1]
          self.composition = cdat[2]
          found_course = True
          break
      if not found_course:
        self.order = 100
        self.composition = False
        print(f'Course {self.course_name} is missing from rename dict')

    # now add in the teacher name if applicable    
    hteacher = student.get_homeroom_teacher()
    
    for teacher in course.teachers:
      if not teacher.sis_id == hteacher.sis_id:
        self.course_name += f' - {teacher.teacher_name}'
      
  # constructor for spgc courses
  @classmethod
  def fromspgc(cls,final = False,*spgc):
    if not spgc:
      return None

    obj = cls.__new__(cls)
    obj.student = spgc[0].student
    obj.course_name = obj.course_rename['Language Arts'][0]
    obj.order = obj.course_rename['Language Arts'][1]
    obj.composition = obj.course_rename['Language Arts'][2]

    # generate some records:
    obj.records = {}
    fscore = Decimal(0.0)
    for period in obj.periods:
      try:
        score = sum([course.records[period.period_id]['score'] for course in spgc])/len(spgc)
        grade = obj.get_ls_letter(score)
        obj.records[period.period_id] = {'grade':grade,'score':score,'comment':None}
      except TypeError as e:
        print(f'Missing grade from SPGC')
        print(f'Student {obj.student.sis_id}')
        print(e)
        obj.records[period.period_id] = {'grade':'','score':None,'comment':None}
    if final:
      try:
        fscore = sum([course.records['final']['score'] for course in spgc])/len(spgc)
        fgrade = obj.get_ls_letter(fscore)
        obj.records['final'] = {'grade':fgrade,'score':fscore}
      except TypeError as e:
        obj.records['final'] = {'grade':'','score':None}
    return obj
  
  @staticmethod
  def get_ls_letter(score):
    # generates a letter based on the 10 pt scale for report courses lacking a letter (SPGC)

    # standardize score to 100 point scale
    if  0 < score <=1:
      score =score*100
    
    # Use 10 point grading scale?
    if score == 0:
      return ''
    elif score < 59.5:
      return 'F'
    elif score < 69.5:
      return 'D'
    elif score < 79.5:
      return 'C'
    elif score < 89.5:
      return 'B'
    elif score <=105:
      return 'A'
    else:
      return 'Error'

class report:
  # what do all of these possible reports have in common?
  # they should all end up as pyhtml div's
  # when called in the report_batch, they should give pyhtml parseable objects
  def __init__(self,*,header = None,table = None):
    self.header = header
    self.table = table
  def pyhtml(self):
    return pyhtml.div(class_=self.__class__.__name__)(self.header,self.table)


class report_card(report):

  # Heading/Header: image, name, grade
  # 
  def __init__(self,student,period,*,cumulative = True,final = False):
    self.student = student
    self.set_periods(period,cumulative = cumulative)
    # self.cumulative = cumulative # I don't think this needs to exist independently of periods
    self.final = final
    self.grade_recs = []
    
    session = Session()
    student = session.merge(student)
    self.term = period.get_term()
    self.set_attendance(final = final)
    # get all active courses for a student
    self.courses = [section.course for section in student.sections if section.course.term.term_id == self.term.term_id]
  
  def set_periods(self,period,*,cumulative = True,sort = True):
    # sets list of periods for all grade_rec instances
    self.periods = []
    if not cumulative:
      self.periods = [period]
    else:
      session = Session()
      session.merge(period)
      for p in session.query(Grading_Period) \
          .filter_by(gp_group_id = period.gp_group_id):
        
        if p.period_id <= period.period_id: # this will have to do until I store dates for grading periods
          self.periods.append(p)
      if sort:
        self.periods.sort(key = lambda period: period.period_id)
  
  def set_attendance(self,*, final = False):
    # pulls attendance records for each period and sticks them into a dict
    #  period_id is the primary key for a list [A,T]

    session = Session()
    student = session.merge(self.student)
    self.attendance = {}
    atotal = Decimal(0.0)
    ttotal = 0
    for period in self.periods:
      # get the record for student,period
      a_rec = session.query(Attendance).filter_by(student_id = self.student.sis_id).filter_by(period_id = period.period_id).one_or_none()
      # if it doesn't exist use 0's
      if not a_rec:
        self.attendance[period.period_id]=['0','0']
      else:
        # if the rec exists, it will have numbers for both
        self.attendance[period.period_id]=[float_to_str(a_rec.absences),str(a_rec.tardies)]
        # get running total if we need final
        atotal += a_rec.absences
        ttotal += a_rec.tardies
    if final:
      self.attendance['final']=[float_to_str(atotal),str(ttotal)]

  def pyhtml_attendance(self,*, final = False):
    # makes a pyhtml table element containing attendance for the given student/period
    
    # start a session and pull in student info
    session = Session()
    student = session.merge(self.student)
    
    a_row = pyhtml.tr(
      pyhtml.td(class_ = "attendance")('Attendance'),
      pyhtml.td(class_ = "att-label")("Absences"),
      [pyhtml.td(class_ = "t-absence")(self.attendance[period.period_id][0]) for period in self.periods],
      pyhtml.td(class_ = "f-absence")(self.attendance['final'][0]) if final else None
    )
    t_row = pyhtml.tr(
      pyhtml.td(class_ = "attendance"),
      pyhtml.td(class_ = "att-label")("Tardies"),
      [pyhtml.td(class_ = "t-tardy")(self.attendance[period.period_id][1]) for period in self.periods],
      pyhtml.td(class_ = "f-tardy")(self.attendance['final'][1]) if final else None
    )
    return pyhtml.table(class_='attendance')(a_row,t_row)

  def pyhtml_heading(self,*,header_image = None,teacher = False):
    # returns a pyhtml div with image, student name, term, (teacher)
    # start with empty list
    elements = []

    # hard code header image size? and place in div
    if header_image:
      image = pyhtml.img(src = header_image,style='float:left;width:10cm;height:2cm;')
      elements.append([pyhtml.div(image)])
    
    # h1 for student name
    elements.append(pyhtml.h1(f'{self.student.common_name} {self.student.last_name}'))

    # h2 for term 
    elements.append(pyhtml.h2(self.term.term_name))
    
    # h2 with the grade level and teacher (IA)
    if teacher:
      elements.append(pyhtml.h2(f'{self.homeroom_teacher.teacher_name if self.homeroom_teacher else "Flagrant Error"}'))
    
    if self.student.graduation_year:
      elements.append(pyhtml.h2(f'Grade {self.student.grade}'))

    return pyhtml.div(class_= "header")(elements)

  def pdf(self,css = None):
    # compiles a pdf of report card
    
    # Set default css
    if not css:
      css='progressreport.css'

    session = Session()
    student = session.merge(self.student)
    period = session.merge(self.periods[-1])

    name = f'{student.last_name} {student.common_name}'
    dirName = f'generated_docs/{period.get_term().term_name}/{period.period_name}'
    title = f'{student.common_name} {student.last_name} {period.period_name} Report Card'

    if not os.path.exists(dirName):
      os.makedirs(dirName)


    hname = f'generated_docs/temp report.html'
    pname = f'{dirName}/{name}.pdf'

    options = {
            'enable-local-file-access': None,
            'page-size': 'letter',
            'orientation': 'portrait',
            'margin-top': '2cm',
            'margin-right': '2cm',
            'margin-bottom': '1cm',
            'margin-left': '2cm',
            'encoding': "UTF-8",
            'disable-smart-shrinking':'',
            'custom-header' : [
              ('Accept-Encoding', 'gzip')
              ]
            }
    
    header = pyhtml.head(pyhtml.title(title),pyhtml.meta(charset = 'UTF-8'),
      pyhtml.link(rel = 'stylesheet',href = str(css)))

    htmldoc = pyhtml.html(header,self.pyhtml())
    
    # write the html
    with open(hname,'w') as html:
      html.write(htmldoc.render())   
    
    
    # now make the pdf
    try:
      pdfkit.from_file(hname, pname, options=options)
      return True
    except Exception as e:
      print(e)

class us_report_card(report_card):
  def __init__(self,student,period,*,final = False):
    report_card.__init__(self,student,period,cumulative = True,final = final)

    # grade_rec period should already be set from within the report_batch

    self.grade_recs = [us_grade_rec(self.student,course,period = period,final = self.final) for course in self.courses]
  
  def pyhtml(self):
    # returns a pyhtml div with student heading, grade records, and attendance
    elements = []
    # 1st is the header image div
    if self.final:
      image = 'SchoolCrestFinal.png'
    else:
      image = 'SchoolCrestReport.png'

    # generate header
    elements.append(self.pyhtml_heading(header_image=image))    

    # table with grades and attendance
    # generate rows and stick them into a table
    rows = []
    # start with the header row
    # Course, Teacher, t1,t1,t3,final
    hrow = pyhtml.tr(class_ = 'header-row')(
      pyhtml.th(class_ = 'course')('Course'),
      pyhtml.th(class_ = 'teacher')('Teacher'),
      [pyhtml.th(class_ = 't-header')(f'T{i+1}') for i in range(len(self.periods))],
      pyhtml.th(class_ = 'final')('Final') if self.final else None)

    rows.append(hrow)
    # next add in data rows from grade_recs
    banding = 'light'
    for rec in self.grade_recs:
      # Course, Teacher, t1, t2, t3, Final
      rows.append(pyhtml.tr(class_=f'grade-row {banding}')(
        pyhtml.td(class_ = 'course')(rec.course_name()),
        pyhtml.td(class_ = 'teacher')(rec.teacher_name()),
        [pyhtml.td(class_ = 'tgrade')(rec.records[period.period_id]['grade']) for period in rec.periods],
        pyhtml.td(class_ = 'fgrade')(rec.records['final']['grade']) if self.final else None))
      # Comment, t1, t2, t3, final %)
      rows.append(pyhtml.tr(class_=f'score-row {banding}')(
        pyhtml.td(class_ = 'comment', colspan = '2')(rec.records[rec.periods[-1].period_id]['comment']),
        [pyhtml.td(class_ = 'tscore')(
                    score_to_print(rec.records[period.period_id]["score"],1)) for period in rec.periods],
        pyhtml.td(class_ = 'fscore')(score_to_round(rec.records['final']['score'])) if self.final else None))
      if banding == 'light':
        banding = 'dark'
      else:
        banding = 'light'
    # compile grade rows into a table
    elements.append(pyhtml.table(rows))

    # tack on attendance table
    elements.append(self.pyhtml_attendance(final = self.final))

    # compile elements into div
    return pyhtml.div(class_=self.__class__.__name__)(elements)

class ls_report_card(report_card):
  def __init__(self,student,period,*,final = False):
    report_card.__init__(self,student,period,cumulative = True,final = final)

    # grade_rec period should already be set from within the report_batch

    self.grade_recs = [ls_grade_rec(self.student,course,period = period,final = self.final) for course in self.courses]

    # get spgc
    spgcs = []
    for grade_rec in self.grade_recs:
      if grade_rec.composition:
        spgcs.append(grade_rec)
    if spgcs:
      spgc = ls_grade_rec.fromspgc(final,*spgcs)
      self.grade_recs.append(spgc)
    else:
      print(f'No spgc for {student.common_name} {student.last_name}')

    

    # order according to grade_rec order value
    self.grade_recs.sort(key=lambda rec: rec.order)

    # get homeroom teacher
    self.homeroom_teacher=student.get_homeroom_teacher()
  
  def pyhtml(self):
    # returns a pyhtml div with student heading, grade records, and attendance
    elements = []
    # 1st is the header image div
    if self.final:
      image = 'SchoolCrestFinal.png'
    else:
      image = 'SchoolCrestReport.png'

    # generate header
    elements.append(self.pyhtml_heading(header_image=image,teacher=True))    

    # table with grades and attendance
    # generate rows and stick them into a table
    rows = []
    # start with the header row
    # Course, t1,t1,t3,final
    rows.append(
      pyhtml.tr(
        pyhtml.th(class_ = 'course')('Course'),
        [pyhtml.th(class_ = 't-header')(f'T{i+1}') for i in range(len(self.periods))],
        pyhtml.th(class_ = 'final')('Final') if self.final else None))
    # next add in data rows from grade_recs
    # also pull out comments for inclusion at the end
    comments = []

    banding = 'light'
    for rec in self.grade_recs:
      comment = rec.records[rec.periods[-1].period_id]['comment']
      if comment:
        comments.append(pyhtml.p(comment))
      # Regular courses
      if not rec.composition:
        # Course, t1, t2, t3, Final
        rows.append(
          pyhtml.tr(class_=f'grade-row {banding}')(
            pyhtml.td(class_ = 'course')(rec.course_name),
            [pyhtml.td(class_ = 'tgrade')(rec.records[period.period_id]['grade']) for period in rec.periods],
            pyhtml.td(class_ = 'fgrade')(rec.records['final']['grade']) if self.final else None))
        #  t1, t2, t3, final %)
        rows.append(pyhtml.tr(class_=f'score-row {banding}')(pyhtml.td(''),
                    [pyhtml.td(class_ = 'tscore')(score_to_print(rec.records[period.period_id]["score"],1)) for period in rec.periods],
                    pyhtml.td(class_ = 'fscore')(score_to_round(rec.records['final']['score'])) if self.final else None))
      
      # SPGC courses
      # we want class course-spgc and score-spgc with course name and most recent score
      elif rec.composition:
        rows.append(
          pyhtml.tr(class_ = f'spgc {banding}')(
            pyhtml.td(class_ = 'course-spgc')(rec.course_name),
            pyhtml.td(class_ = 'score-spgc',colspan = '4')(score_to_print(rec.records[rec.periods[-1].period_id]['score'],1)),
            [pyhtml.td() for i in range(len(rec.records))] )) # hopefully skips the last n columns?
      if banding == 'light':
        banding = 'dark'
      else:
        banding = 'light'

    # compile rows into a table
    elements.append(pyhtml.table(rows))

    # tack on attendance table
    elements.append(self.pyhtml_attendance(final=self.final))
    
    # add in comments div at bottom
    elements.append(pyhtml.div(class_='comments')(comments))

    # compile elements into div
    return pyhtml.div(class_=self.__class__.__name__)(elements)

class cs_report_card(report_card):
  def __init__(self,student,period,*,final = False):
    report_card.__init__(self,student,period,cumulative = True,final = final)

    # grade_rec period should already be set from within the report_batch

    self.grade_recs = [grade_rec(self.student,course,period = period,final = self.final) for course in self.courses]
  
  def pyhtml(self):
    # returns a pyhtml div with student heading, grade records, and attendance
    elements = []
    # generate header
    elements.append(self.pyhtml_heading(header_image='../School-CS-logo.jpg'))    

    # table with grades and attendance
    
    # 2nd element is the h1 with student name
    # elements.append(pyhtml.h1(f'{self.student.common_name} {self.student.last_name}'))


    # 3rd: term for report (h2?)
    # elements.append(pyhtml.h2(self.term.term_name))

    # 4th is the table with grades and attendance
    # generate rows and stick them into a table
    rows = []
    # start with the header row
    # Course, Teacher, t1,t1,t3,final
    rows.append(
      pyhtml.tr(class_ = 'header-row')(
        pyhtml.th(class_ = 'course')('Course'),
        pyhtml.th(class_ = 'teacher')('Teacher'),
        [pyhtml.th(class_ = 't-header')(f'T{i+1}') for i in range(len(self.periods))],
        pyhtml.th(class_ = 'final')('Final') if self.final else None))
    # next add in data rows from grade_recs
    banding = 'light'
    for rec in self.grade_recs:
      # Course, Teacher, t1, t2, t3, Final
      rows.append(pyhtml.tr(class_=f'grade-row {banding}')(pyhtml.td(class_ = 'course')(rec.course_name()),
                  pyhtml.td(class_ = 'teacher')(rec.teacher_name()),
                  [pyhtml.td(class_ = 'tgrade')(rec.records[period.period_id]['grade']) for period in rec.periods],
                  pyhtml.td(class_ = 'fgrade')(rec.records['final']['grade']) if self.final else None))
      # Comment, t1, t2, t3, final %)
      rows.append(pyhtml.tr(class_=f'score-row {banding}')(pyhtml.td(class_ = 'comment', colspan = '2')(rec.records[rec.periods[-1].period_id]['comment']),
                  [pyhtml.td(class_ = 'tscore')(
                    score_to_print(rec.records[period.period_id]["score"],1)) for period in rec.periods],
        pyhtml.td(class_ = 'fscore')(score_to_round(rec.records['final']['score'])) if self.final else None))
      if banding == 'light':
        banding = 'dark'
      else:
        banding = 'light'
    # compile grade rows into a table
    elements.append(pyhtml.table(rows))

    # compile elements into div
    return pyhtml.div(class_=self.__class__.__name__)(elements)



class report_batch:
  # report_batch holds data and methods for handling html display of multple or single reports
  # every batch should have html header
  # eventually? these should generate/use their own .css; for now link to external one
  # encoding?

  def __init__(self,*,css = None,encoding = 'UTF-8',reports = None,title = None):
    # list or empty list of reports
    if not reports:
      self.reports = []
    else:
      self.reports = reports
    
    # use title or generate one based on date
    if not title:
      self.__title = f'Untitled Report {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}'
    else:
      self.__title = str(title)
    
    # header can include css file or not
    if not css:
      self.__head = pyhtml.head(pyhtml.title(self.__title),pyhtml.meta(charset = str(encoding)))
    else:
      self.css = css
      self.__head = pyhtml.head(pyhtml.title(self.__title),pyhtml.meta(charset = str(encoding)),
      pyhtml.link(rel = 'stylesheet',href = str(css)))
    
  
  def __str__(self):
    return pyhtml.html(self.__head,self.reports).render()
  
  def __repr__(self):
    return f'Report Batch Object: \n{str(self)}'

  def add_report(self,report):
    self.reports.append(report)

  def pdf(self,*,name = None,options = None):
    # compiles a pdf with all reports

    if not name:
      name = canvas_site().get_current_period().period_name

    hname = f'generated_docs/{canvas_site().get_current_term().term_name}/{name}.html'
    pname = f'generated_docs/{canvas_site().get_current_term().term_name}/{name}.pdf'

    if not options:
      options = {
              'enable-local-file-access': None,
              'page-size': 'letter',
              'orientation': 'portrait',
              'margin-top': '2cm',
              'margin-right': '2cm',
              'margin-bottom': '1cm',
              'margin-left': '2cm',
              'encoding': "UTF-8",
              'disable-smart-shrinking':'',
              'custom-header' : [
                ('Accept-Encoding', 'gzip')
                ]
              }
    
    # write the html
    with open(hname,'w') as html:
      html.write(str(self))   
    
    
    # now make the pdf
    try:
      pdfkit.from_file(hname, pname, options=options)
      return True
    except Exception as e:
      print(e)


#### Odds and ends

# Formatting functions

def float_to_str(f):
  # Convert the given float to a string,
  # without scientific notation
  # mostly/only used for attendance
  if not f:
    return '0'
  
  with localcontext() as context:

    d1 = context.create_decimal(str(f))
    return format(d1, 'f').rstrip('0').rstrip('.')

def score_to_print(score,places=1):
  if not score:
    return ''
  elif places == 1:
    score=Decimal(score)
    return f'{score:.1f}%'
  elif places == 0:
    score=Decimal(score)
    return f'{score:.0f}%'

def score_to_round(score):
  if not score:
    return score
  try:
    return f'{round(score)}%'
  except Exception as e:
    print(e)
    return score