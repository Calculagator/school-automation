# Module: schoolattendance.py
# contains functions/classes printing attendance roll books from the local db

from model import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, Session
import pandas

# How many dates to put per page
dates_per_page = 18

# School Calendar
start_date = pandas.datetime(2020,3,10)
end_date = pandas.datetime(2020,5,22)

# School Holidays 19-20:
# Thanksgiving
school_holidays = pandas.period_range('11/25/2019', '11/29/2019', freq='D')
# Christmas
school_holidays = school_holidays.append(pandas.period_range('12/20/2019', '1/06/2020', freq='D'))
# Spring Break
school_holidays = school_holidays.append(pandas.period_range('3/2/2020', '3/6/2019', freq='D'))

school_days = pandas.offsets.CustomBusinessDay(holidays=school_holidays,weekmask = 'Tue Wed Thu Fri')
p_school_days = pandas.offsets.CustomBusinessDay(holidays=school_holidays,weekmask = 'Tue Wed Thu')
k_school_days = pandas.offsets.CustomBusinessDay(holidays=school_holidays,weekmask = 'Tue Thu')

# School full years:
school_year = pandas.date_range(start_date,end_date,freq=school_days)
p_school_year = pandas.date_range(start_date,end_date,freq=p_school_days)
k_school_year = pandas.date_range(start_date,end_date,freq=k_school_days)

# Variable for figuring grade levels
# Current term
current_term_name = '2019-2020'
# Pull the correct term from the db ** must be populated from db first
try:
  session = Session()
  current_term = session.query(Term).filter_by(
      term_name=current_term_name).one()
  print(f'Current term is {current_term.term_name}')
except:
  print('Unable to determine current term. Try updating the terms in the database first.')
  current_term = None


def write_html_header(file, css='attendance.css'):
    # Takes open file for writing and optional css url
    # writes the header template and body open tag
    file.write(
            f"<!DOCTYPE html>"
            f"<html>"
            f"<head>"
            f"<link rel=\"stylesheet\" href=\"{css}\">"
            f"<meta charset=UTF-8>"
            f"</head>"
            f"<body>"
            f"<div class=\"attendance\">"
            )


def write_sheet_header(file, section):

  # get a course name with section:
  if section.course.full_name == section.section_name:
    course_name = section.section_name
  else:
    course_name = f'{section.course.full_name} {section.section_name}'
  file.write(
        f"<h1>School Roll Book 2019-2020</h1>"
        f"<h2> <span class=\"course\">{course_name}</span>"
        f"<span class=\"teacher\">{section.course.teachers[0].teacher_name}</span></h2>"
    )
def write_sheet_table_header(file,dates):

    # start with a blank for student name header
    file.write(
        "<table>"
        "<thead>"
        "<tr>"
        '<th><div class="nameblank"></div></th>'
        )
    # Span each month the number of days that are in daterange
    # count through the the dates -when we reach a new month or the end, write the previous one
    col_span = 0
    month = dates[0].month
    for i in range(len(dates)):
      if dates[i].month == month:
        col_span += 1
      else: # new month triggers writing the previous and resetting the counter
        file.write(f'<th class="month" colspan="{col_span}">{dates[i-1].month_name()}</th>')
        col_span = 1
        month = dates[i].month
        
      if i == len(dates)-1: # last entry triggers writing and the end of row
        file.write(f'<th class="month" colspan="{col_span}">{dates[i].month_name()}</th>'
        '</tr>'
        )
    # another blank cell for new line
    file.write("<tr>"
        '<th><div class="nameblank"></div></th>'
        )
    # go through dates and write day and number
    for date in dates:
      file.write('<th><div class="day">'
                f'{date.day_name()[0:2]}'
                '<br>'
                f'{date.day}'
                '</div></th>'
      )     
    file.write("</tr>"
            "</thead>"
            "<tbody>"
        )
def write_sheet_name_row(file,name,length):
  file.write('<tr>'
            f'<td class="name">{name}</td>'
  )
  for _i in range(length): # blank cell for every date
    file.write(f'<td class="cell"></td>')
  file.write('</tr>')

def write_sheet_foot(file):
  file.write('</tbody>'
            '</table>'
            '<div class="instructions">'
            'Attendance will be collected 9:00-9:30. <br>'
            'Please make a check for present students and write an A for absent students'
            '</div>'
        )
def write_html_foot(file):
  file.write('</div>'
            '</body>'
            '</html>'
            )




def write_sheet(file,section):

  # figure out which set of dates to use
  if section.course.sis_id[6] == 'P':
    if section.course.sis_id[8] in ['0','K']:
      s_year = k_school_year
    else:
      s_year = p_school_year
  else:
    s_year = school_year
  
  # split up school year into chunks according to dates_per_page
  for i in range(0,len(s_year)-1,dates_per_page):
    # Write the header
    write_sheet_header(file,section)
    
    dates = s_year[i:i+dates_per_page]
    # Start the table
    write_sheet_table_header(file,dates)

    # write a row for each student
    for student in section.students:
      write_sheet_name_row(file,f'{student.last_name}, {student.first_name}', len(dates))

    # End the table
    write_sheet_foot(file)

  
def write_attendance_sm(current_term=current_term):
  
  # Open the file for writing
  with open("generated_docs/School-SM-Attendance.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get all courses from the current term
    session = Session()
    courses = session.query(Course).filter_by(term_id = current_term.term_id).order_by(Course.sis_id).all()

    # go through all courses
    for course in courses:
      # skip all non-homeroom ls courses
      if  course.sis_id[4:6]=='SM' and (course.homeroom or course.sis_id[6] == 'U'):
        # write a roster for each section that isn't empty
        for section in course.sections:
          if len(section.students):
            write_sheet(file, section)

    # Close out the html
    write_html_foot(file)

def write_attendance_ch(current_term=current_term):
  
  # Open the file for writing
  with open("generated_docs/School-CH-Attendance.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get all courses from the current term
    session = Session()
    courses = session.query(Course).filter_by(term_id = current_term.term_id).order_by(Course.sis_id).all()

    # go through all courses
    for course in courses:
      # skip all non-homeroom ls courses
      if  course.sis_id[4:6]=='CH' and (course.homeroom or course.sis_id[6] == 'U'):
        # write a roster for each section that isn't empty
        for section in course.sections:
          if len(section.students):
            write_sheet(file, section)

    # Close out the html
    write_html_foot(file)

def write_attendance_in(current_term=current_term):
  
  # Open the file for writing
  with open("generated_docs/School-IN-Attendance.html","w") as file:
    # Start the HTML document
    write_html_header(file)
    # get all courses from the current term
    session = Session()
    courses = session.query(Course).filter_by(term_id = current_term.term_id).order_by(Course.sis_id).all()

    # go through all courses
    for course in courses:
      # skip all non-homeroom ls courses
      if  course.sis_id[4:6]=='SI' and (course.homeroom or course.sis_id[6] == 'U'):
        # write a roster for each section that isn't empty
        for section in course.sections:
          if len(section.students):
            write_sheet(file, section)

    # Close out the html
    write_html_foot(file)