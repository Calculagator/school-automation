# Module accounts.py

from model import Student, Parent, Teacher, Term, GP_Group, \
  Grading_Period, Course, Section, Grade_Record, Attendance, \
    Grading_Standard, Account, canvas_site, Session, crm_site
from dotenv import load_dotenv
from os import getenv
load_dotenv()

from time import sleep
# sending emails
import smtplib
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import charset
from email.utils import formatdate, make_msgid
charset.add_charset('utf-8', charset.SHORTEST, charset.QP) # stop base64 encoding utf-8


from email.utils import formatdate


import pandas # export list of students?
## What to do for user accounts

# export students from google (only students or all)
# read export as a dataframe
# can update existing users with **** !!!!!!!!!
# remove any non-students from DF
# loop through df; 
# if students aren't active in canvas, set status to "Suspended"
# and change Org Unit Path to /Suspended
# set recovery email to parent[0] email and phone to parent[0] phone
# if Last Sign in is "Never Logged in" set the new password from db
# if there is a sign in, set db password to None

# go through active students in DB
# if their email isn't in DF, add in fname,lname,email,password, Org Unit Path /School CH-IN-sM/School Louisville/Students
# recovery email, recoery phone, department, Change password = TRUE
def generate_google_accounts(*,input_file = None,output_file = None):
  if not input_file:
    input_file = f'./google_accounts/users.csv'
  if not output_file:
    output_file = f'./google_accounts/{getenv("current_term_name")}.csv'
  
  # import csv
  df = pandas.read_csv(input_file,sep=',')
  # drop the unused columns?
  df = df.drop(columns = [
    'New Primary Email [UPLOAD ONLY]',
    'Work Secondary Email',
    'Password Hash Function [UPLOAD ONLY]',
    'Status [READ ONLY]',
    'Work Phone',
    'Home Phone',
    'Mobile Phone',
    'Work Address',
    'Home Address',
    'Employee ID',
    'Employee Type',
    'Employee Title',
    'Manager Email',
    'Cost Center',
    '2sv Enrolled [READ ONLY]',
    '2sv Enforced [READ ONLY]',
    'Building ID',
    'Floor Name',
    'Floor Section',
    'Email Usage [READ ONLY]',
    'Drive Usage [READ ONLY]',
    'Total Storage [READ ONLY]'    
  ])
  user_dict = df.to_dict(orient='records')
  
  # remove non-students?
  user_dict[:] = [row for row in user_dict if row['Org Unit Path [Required]'] == '/School CH-IN-SM/School Louisville/Students']
  
  # start session for DB lookups
  session = Session()
  # iterate through and make changes
  for row in user_dict:
    # deactive inactive/missing students
    student = session.query(Student).filter_by(email = row['Email Address [Required]']).one_or_none()
    if not student or not student.active:
      row['New Status [UPLOAD ONLY]']='Suspended'
      row['Org Unit Path [Required]']='/Suspended'

    #  for existing students
    else:
      # set recovery info
      row['Recovery Email'] = student.parents[0].email
      row['Home Secondary Email'] = student.parents[0].email
      row['Recovery Phone [MUST BE IN THE E.164 FORMAT]'] = f'+1{student.parents[0].phone}'
      # set new password if needed and remove from DB if not
      if row['Last Sign In [READ ONLY]']=='Never logged in':
        row['Password [Required]']=student.password
      else:
        student.password = None
    session.commit()
  # convert back to DF?
  df = pandas.DataFrame(user_dict)
  # now check all students to be sure they are in data
  students = session.query(Student).filter_by(active = True).all()
  for student in students:
    if student.email not in df['Email Address [Required]'].values:
      student_dict = {
        'First Name [Required]': student.common_name, 
        'Last Name [Required]': student.last_name, 
        'Email Address [Required]': student.email, 
        'Password [Required]': student.password, 
        'Org Unit Path [Required]': '/School CH-IN-SM/School Louisville/Students', 
        'Recovery Email': student.parents[0].email, 
        'Home Secondary Email': student.parents[0].email, 
        'Recovery Phone [MUST BE IN THE E.164 FORMAT]': f'+1{student.parents[0].phone}', 
        'Department': student.graduation_year - 2000, 
        'Change Password at Next Sign-In': True, 
        'New Status [UPLOAD ONLY]': 'Active',
        'Last Sign In [READ ONLY]': None
        }
      print(f'{student.email} added to .csv') 
      df = df.append(student_dict,ignore_index=True)
  df.to_csv(output_file,index=False)


def email_student_login_info():
  # go through list of active parents?
  # Generic greeting with student account info, links, etc
  # for each ACTIVE student:
    # give name, email
    # if there is a password, give it with instructions to set a password
    # if no password, give instructions to reset password
    # give recovery email/phone info

  emails_sent = 0
  from_email = "Example School <it@example.com>"
  subject = "School Canvas Student Accounts"
  
  # loop through parents
  session = Session()
  parents = session.query(Parent).filter_by(active = True).all()
  messages = [] # add message for each parent
  for parent in parents:

    msg = MIMEMultipart('alternative')
    msg['Message-ID'] = make_msgid(domain='example.com')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = f'{parent.first_name} {parent.last_name} <{parent.email}>'
    msg['Date'] = formatdate()
    text = ('Dear Parents,' +
            'We recently sent out instructions for how to log into Canvas with ' +
            'parent/observer accounts.\n' +
            'Student accounts are now ready as well. These student accounts will be used ' +
            'if assignments must be submitted online. Students can log into canvas by ' +
            'going to https://canvas.example.com/login/google and using the ' +
            'school account credentials provided below.\n' +
            'If any of the account recovery contact info given below is incorrect, ' +
            'please respond to this email and give the correct contact info.'
            )

    html = (
        f'<div dir="ltr">Dear Parents,' +
        f'<div>We recently sent out instructions for how to log into Canvas with parent/observer accounts.</div>' +
        f'<div>Student accounts are now ready as well. These student accounts will be used if assignments must be submitted online. Students can log into canvas by going to ' +
        f'<a href="https://canvas.example.com/login/google">https://canvas.example.com/login/google</a> ' +
        f'and using the school account credentials provided below.</div>' +
        f'<div>If any of the account recovery contact info given below is incorrect, please respond ' +
        f'to this email and give the correct contact info.</div><div><br></div>'
      )
    # set a check for only primary students:
    primary = True

    # loop through students and add account info
    for student in parent.students:
      # Skip inactive students
      if not student.active:
        continue
      
      # Skip primary students and parents with only primary students
      if student.grade < 3:
        continue  
      
      # it's possible all students could be skipped: only send email if value of 'primary' is changed
      primary = False
      
      text += f'\n{student.common_name} {student.last_name}\n'
      text += f'{student.email}\n'

      html += f'<div>{student.common_name} {student.last_name}</div>'
      html += f'<div><a href="mailto:{student.email}">{student.email}</a></div>'

      # instructions for existing passwords
      if not student.password:
        text += (
            f'The password for this account has already been set. If you need to reset ' +
            f'it, you may do so by going to https://accounts.google.com, entering the ' +
            f'email, and following the "Forgot Password" link and prompts. The recovery ' +
            f'phone number and email for this account are '
          )
        html += (
            f'<div>The password for this account has already been set. If you need to reset it, you may do so by going to ' +
            f'<a href="https://accounts.google.com">https://accounts.google.com</a>' +
            f', entering the email, and following the &quot;Forgot Password&quot; link and prompts. ' +
            f'The recovery phone number and email for this account are '
          )
      else: # instructions for new passwords
        text += (
            f'The temporary password for this account is {student.password}\n' +
            f'Please go to https://accounts.google.com to log in and set a' +
            f'password before logging into Canvas. Should you ever need to reset the ' +
            f'password for this account, the recovery phone number and email are '
          )
        html += (
            f'<div>The temporary password for this account is <font face="monospace" size="4">{student.password}</font>' +
            f'<br>Please go to <a href="https://accounts.google.com">https://accounts.google.com</a>' +
            f' to log in and set a password before logging into Canvas. Should you ever need to reset ' +
            f'the password for this account, the recovery phone number and email are '
          )
      # recovery for all students
      text += f'{student.parents[0].phone} and {student.parents[0].email}, respectively.\n'
      html += (
          f'{student.parents[0].phone} and ' +
          f'<a href="mailto:{student.parents[0].email}">{student.parents[0].email}</a>, ' +
          f'respectively.</div><br></div>'
        )
    # only send emails that have students
    if primary:
      continue

    part1 = MIMEText(text,'plain', _charset='utf-8')
    part2 = MIMEText(html,'html', _charset='utf-8')
    msg.attach(part1)
    msg.attach(part2)
    messages.append(msg)
    print(f'Emailto parent {parent.email} added to queue')
  print(f'{len(messages)} messages added to queue')
  try:
    with smtplib.SMTP("smtp-relay.gmail.com", 25) as server:
    # with smtplib.SMTP("smtp.mailtrap.io", 2525) as server:
      # server.login("bd2529fbceb904", "385b2662956e62")
      emails_sent = 0 # keep track of successful sends?
      for msg in messages:
        server.send_message(msg)
        emails_sent += 1
        print(f'Email {emails_sent} sent to {msg["To"]}')
      print(f'{emails_sent} emails sent to parents')
      # input("Press a key to continue")
      sleep(3)
  except Exception as e:
    print(e)
    print(f'Problem sending emails')
    print(f'{emails_sent} emails sent to parents')

