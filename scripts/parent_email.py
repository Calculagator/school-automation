# Module parent_email.py

from model import Student, Parent, Teacher, Term, GP_Group, Grading_Period, Course, Section, Grade_Record, Attendance, canvas_site, Session, crm_site
from time import sleep
# sending emails
import smtplib
from email.message import EmailMessage
from email.utils import formatdate

sender = "School Canvas <canvas@example.com>"
from_email = "Joel Amunrud for School <jamunrud@example.com>"

recipient = "A Parent <parent@smtp.mailtrap.io>"

# need to get only the active parents 
session = Session()
parents = session.query(Parent).filter(Parent.active == True).filter_by(last_name = 'Shinabery').all()

# loop through parents and send emails
# skip = True
skip = False
for parent in parents:
    # skip up to Geddes
    
    if parent.crm_id == '1298':
        skip = False
    if skip:
        continue
    if not parent.students:
        continue

    msg = EmailMessage()
    

    # me == the sender's email address
    # you == the recipient's email address
    msg['Subject'] = f'Canvas accounts for School Students'
    msg['From'] = from_email
    # msg['Sender'] = sender # this may cause spam problems
    msg['To'] = f'{parent.first_name} {parent.last_name} <{parent.email}>'
    msg["Date"] = formatdate(localtime=True)

    body = f'''Dear {parent.first_name},\n
Many School 3rd-12th grade teachers will begin using Canvas to provide class information \
and collect assignments. Your student can login with the Student ID and password below. \n
Canvas: http://canvas.example.com\n'''
    stu_count = 0
    for student in parent.students:
        if student.first_name \
            and student.sis_id \
            and student.password:
            if student.grade > 2:
                body += f'\nFor {student.first_name}\n  ID: {student.sis_id}\n  Password: {student.password}\n'
                stu_count += 1
        else:
            print(f'Error with student {student.canvas_id}')


    msg.set_content(body)
    # if email doesn't have any student info (kids are too young), skip it
    if not stu_count:
        continue
    count = 0
    while True:
        try:
            # with smtplib.SMTP("smtp-relay.gmail.com", 25) as server:
            with smtplib.SMTP("smtp.mailtrap.io", 2525) as server:
                server.login("bd2529fbceb904", "385b2662956e62")
                server.send_message(msg)
                print(f'Email sent to parent {parent.crm_id}')
                # sleep(2)
                break
        except Exception as e:
            print(e)
            count += 1
            print(f'Problem with parent {parent.crm_id}')
            sleep(60*count)

        
        