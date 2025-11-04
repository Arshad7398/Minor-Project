from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
import random
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import os
import csv
from io import TextIOWrapper, BytesIO
from PyPDF2 import PdfMerger
import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from pathlib import Path
from zipfile import ZipFile

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///timetable.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your_secret_key_here'
db = SQLAlchemy(app)

# Database Models
class Classroom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    building_id = db.Column(db.Integer, db.ForeignKey('building.id'), nullable=False)

class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    credits = db.Column(db.Integer, nullable=False)
    is_lab = db.Column(db.Boolean, default=False)
    priority = db.Column(db.Boolean, default=False)# for 2 hour class
    priority_morning = db.Column(db.Boolean, default=False)# for morning shift
    priority_evening = db.Column(db.Boolean, default=False)# for evening shif
    avoid_day = db.Column(db.Integer, default=-1)# to avoid any day
    professor_id = db.Column(db.Integer, db.ForeignKey('professor.id'), nullable=True)
    lab_professor_id = db.Column(db.Integer, db.ForeignKey('professor.id'), nullable=True)
    lab_id1 = db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=True)
    lab_id2= db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=True)
    lab_id3 = db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=True)
    batch_id= db.Column(db.Integer, db.ForeignKey('batch.id'),nullable=True)

class Building(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    # Relationship: One building → many classrooms
    classrooms = db.relationship('Classroom', backref='building', lazy=True)

class Professor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    #email = db.Column(db.String(100), nullable=False, unique=True)

    priority_classroom_1 = db.Column(db.Integer, db.ForeignKey('building.id'), nullable=True)
    priority_classroom_2 = db.Column(db.Integer, db.ForeignKey('building.id'), nullable=True)
    priority_classroom_3 = db.Column(db.Integer, db.ForeignKey('building.id'), nullable=True)
    #department = db.Column(db.String(50), nullable=False)
    #designation = db.Column(db.String(50))  # e.g., Lecturer, Assistant Prof, etc.
    #max_hours_per_day = db.Column(db.Integer, default=6)  # for timetable allocation

    # Optional: courses assigned to this professor (many-to-many)

class Lab(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)

class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    courses = db.relationship('Course', backref='batch', lazy=True)

class Schedule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('batch.id'), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True)
    lab_id = db.Column(db.Integer, db.ForeignKey('lab.id'), nullable=True)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    professor_id = db.Column(db.Integer, db.ForeignKey('professor.id'), nullable=False)
    day = db.Column(db.Integer, nullable=False)  # 0-4 for Monday-Friday
    slot = db.Column(db.Integer, nullable=False)  # 0-8 for time slots

def find_available_classroom_with_priorityroom(day, slot,classroom_id,batch):
    classrooms = Classroom.query.filter_by(building_id=classroom_id)
    for classroom in classrooms:
        if batch.capacity > classroom.capacity:
            continue
        slot_occupied = Schedule.query.filter_by(
            classroom_id=classroom.id, day=day, slot=slot
        ).first()
        slot_occupied2 = Schedule.query.filter_by(
            classroom_id=classroom.id, day=day, slot=slot+1
        ).first()
        if not (slot_occupied or slot_occupied2):
            return classroom  # classroom is free for both slots
    return None

def find_available_classroom(day, slot , batch):
    all_classrooms = Classroom.query.all()
    for classroom in all_classrooms:
        if batch.capacity > classroom.capacity:
            continue
        slot_occupied = Schedule.query.filter_by(
            classroom_id=classroom.id, day=day, slot=slot
        ).first()
        next_slot_occupied = Schedule.query.filter_by(
            classroom_id=classroom.id, day=day, slot=slot + 1
        ).first()

        if not slot_occupied and not next_slot_occupied:
            return classroom  # classroom is free for both slots
    return None

def find_available_classroom_with_priorityroom_onehour(day,slot,classroom_id,batch):
    classrooms = Classroom.query.filter_by(building_id=classroom_id)
    for classroom in classrooms:
        if batch.capacity > classroom.capacity:
            continue
        slot_occupied = Schedule.query.filter_by(
            classroom_id=classroom.id, day=day, slot=slot
        ).first()
        if not slot_occupied:
            return classroom  # classroom is free for both slots
    return None

def find_available_classroom_onehour(day,slot,batch):
    all_classrooms = Classroom.query.all()
    for classroom in all_classrooms:
        if batch.capacity > classroom.capacity:
            continue
        slot_occupied = Schedule.query.filter_by(
            classroom_id=classroom.id, day=day, slot=slot
        ).first()

        if not slot_occupied:
            return classroom  # classroom is free for both slots
    return None

def find_available_lab(day, slot,id,batch):
    all_labs=[]
    if id==-1:
        all_labs = Lab.query.all()
    else:
        all_labs = Lab.query.filter_by(id=id).all()
    for lab in all_labs:
        if batch.capacity > lab.capacity:
            continue
        slot_occupied = Schedule.query.filter_by(
            lab_id=lab.id, day=day, slot=slot
        ).first()
        slot_occupied2 = Schedule.query.filter_by(
            lab_id=lab.id, day=day, slot=slot+1
        ).first()
        if not (slot_occupied or slot_occupied2):
            return lab  # classroom is free for both slots
    return None

def is_slot_available(course, day, slot, building_id,batch):
    existing_schedule = Schedule.query.filter_by(
        batch_id=course["batch_id"], day=day, slot=slot
    ).first()
    professor_schedule = Schedule.query.filter_by(
        professor_id=course["professor_id"], day=day, slot=slot
    ).first()
    if existing_schedule or professor_schedule:
        return False
    classrooms=None
    if(building_id==-1):
        classrooms=Classroom.query.all()
    else :
        classrooms=Classroom.query.filter_by(building_id=building_id)

    for classroom in classrooms:
        if batch.capacity > classroom.capacity:
            continue
        classroom_schedule = Schedule.query.filter_by(
            classroom_id=classroom.id, day=day, slot=slot
        ).first()

        if not classroom_schedule:
            return True
    return False

def is_slot_available_lab_priority1(course, day, slot,batch, is_lab=False):
    # batch = Batch.query.filter(Batch.id == course.batch_id).first()
    lab=Lab.query.filter_by(id=course.lab_id1).first()
    if batch.capacity>lab.capacity:
        return False
    existing_schedule = Schedule.query.filter_by(
        batch_id=course.batch_id, day=day, slot=slot
    ).first()
    professor_schedule = Schedule.query.filter_by(
        professor_id=course.lab_professor_id, day=day, slot=slot
    ).first()
    lab_schedule = Schedule.query.filter_by(
        lab_id=course.lab_id1, day=day, slot=slot
    ).first()

    existing_schedule2 = Schedule.query.filter_by(
        batch_id=course.batch_id, day=day, slot=slot+1
    ).first()
    professor_schedule2 = Schedule.query.filter_by(
        professor_id=course.lab_professor_id, day=day, slot=slot+1
    ).first()
    lab_schedule2 = Schedule.query.filter_by(
        lab_id=course.lab_id1, day=day, slot=slot+1
    ).first()
    return not (existing_schedule or professor_schedule or lab_schedule or existing_schedule2 or professor_schedule2 or lab_schedule2)

def is_slot_available_lab_priority2(course, day, slot,batch, is_lab=False):
    lab=Lab.query.filter_by(id=course.lab_id2).first()
    if batch.capacity>lab.capacity:
        return False
    existing_schedule = Schedule.query.filter_by(
        batch_id=course.batch_id, day=day, slot=slot
    ).first()
    professor_schedule = Schedule.query.filter_by(
        professor_id=course.lab_professor_id, day=day, slot=slot
    ).first()
    lab_schedule = Schedule.query.filter_by(
        lab_id=course.lab_id2, day=day, slot=slot
    ).first()

    existing_schedule2 = Schedule.query.filter_by(
        batch_id=course.batch_id, day=day, slot=slot+1
    ).first()
    professor_schedule2 = Schedule.query.filter_by(
        professor_id=course.lab_professor_id, day=day, slot=slot+1
    ).first()
    lab_schedule2 = Schedule.query.filter_by(
        lab_id=course.lab_id2, day=day, slot=slot+1
    ).first()
    return not (existing_schedule or professor_schedule or lab_schedule or existing_schedule2 or professor_schedule2 or lab_schedule2)

def is_slot_available_lab_priority3(course, day, slot,batch, is_lab=False):
    lab=Lab.query.filter_by(id=course.lab_id3).first()
    if batch.capacity>lab.capacity:
        return False
    existing_schedule = Schedule.query.filter_by(
        batch_id=course.batch_id, day=day, slot=slot
    ).first()
    professor_schedule = Schedule.query.filter_by(
        professor_id=course.lab_professor_id, day=day, slot=slot
    ).first()
    lab_schedule = Schedule.query.filter_by(
        lab_id=course.lab_id3, day=day, slot=slot
    ).first()

    existing_schedule2 = Schedule.query.filter_by(
        batch_id=course.batch_id, day=day, slot=slot+1
    ).first()
    professor_schedule2 = Schedule.query.filter_by(
        professor_id=course.lab_professor_id, day=day, slot=slot+1
    ).first()
    lab_schedule2 = Schedule.query.filter_by(
        lab_id=course.lab_id3, day=day, slot=slot+1
    ).first()
    return not (existing_schedule2 or professor_schedule2 or lab_schedule2 or existing_schedule or professor_schedule or lab_schedule)

def is_slot_available_lab(course, day, slot, is_lab=False):
    existing_schedule = Schedule.query.filter_by(
        batch_id=course.batch_id, day=day, slot=slot
    ).first()
    professor_schedule = Schedule.query.filter_by(
        professor_id=course.lab_professor_id, day=day, slot=slot
    ).first()
    return not (existing_schedule or professor_schedule)

def generate_excel(batch_ids):
    if not batch_ids:
        return None

    batch = Batch.query.get(batch_ids[0])
    if not batch:
        return None

    time_slots = [
        "08:00 AM - 09:00 AM", "09:00 AM - 10:00 AM", "10:00 AM - 11:00 AM",
        "11:00 AM - 12:00 PM", "12:00 PM - 01:00 PM", "01:00 PM - 02:00 PM",
        "02:00 PM - 03:00 PM", "03:00 PM - 04:00 PM", "04:00 PM - 05:00 PM"
    ]
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    timetable = [["" for _ in range(9)] for _ in range(5)]
    
    # Set lunch break for all days at slot 4 (12:00 PM - 1:00 PM)
    # for day in range(5):
    timetable[2][4] = "Lunch"
    schedules = Schedule.query.filter_by(batch_id=batch.id).all()

    for schedule in schedules:
        if schedule.slot == 4:  # Skip lunch slot
            continue
        course = Course.query.get(schedule.course_id)
        professor = Professor.query.get(schedule.professor_id)
        classroom = Classroom.query.get(schedule.classroom_id)
        lab = Lab.query.get(schedule.lab_id)
        
        entry = f"{course.name} ({professor.name})"
        if lab:
            entry += f" [{lab.name}]"
        if classroom:
            entry += f" {{{classroom.name}}}"
            
        timetable[schedule.day][schedule.slot] = entry

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"TimeTable"

    ws['A1'] = f"Timetable for Batch: {batch.name}"
    ws['A1'].font = Font(size=14, bold=True)
    ws.merge_cells('A1:J1')

    ws['A2'] = "Day"
    for col_index, time_slot in enumerate(time_slots, start=2):
        col_letter = get_column_letter(col_index)
        ws[f'{col_letter}2'] = time_slot

    for day_index, day_name in enumerate(days):
        ws[f"A{day_index + 3}"] = day_name
        for slot_index, slot_content in enumerate(timetable[day_index]):
            col_letter = get_column_letter(slot_index + 2)
            ws[f"{col_letter}{day_index + 3}"] = slot_content

    current_dir = Path(__file__).parent
    timetables_dir = current_dir / "timetables"
    timetables_dir.mkdir(exist_ok=True)
    excel_path = timetables_dir / f"batch_{batch.id}.xlsx"
    wb.save(excel_path)
    
    return excel_path

# Routes
@app.route('/')
def index():
    batches = Batch.query.all()
    return render_template('index.html', batches=batches)
@app.route('/select_batches', methods=['GET'])
def select_batches():
    batches = Batch.query.all()
    return render_template('select_batches.html', batches=batches)

@app.route('/download-timetable', methods=['POST'])
def download_timetable():
    selected_batch_ids = request.form.getlist('batch_ids[]')
    if not selected_batch_ids:
        flash('No batches selected', 'error')
        return redirect(url_for('index'))

    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, 'w') as zip_file:
        for batch_id in selected_batch_ids:
            excel_path = generate_excel([int(batch_id)])
            if excel_path and os.path.exists(excel_path):
                zip_file.write(excel_path, os.path.basename(excel_path))
                os.remove(excel_path)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='timetables.zip'
    )

@app.route('/create_batch', methods=['GET', 'POST'])
def create_batch():
    if request.method == 'POST':
        batch_name = request.form['name']
        capacity = request.form.get('capacity')
        new_batch = Batch(name=batch_name,capacity=int(capacity))
        db.session.add(new_batch)
        try:
            db.session.commit()
            flash('Batch created successfully', 'success')
        except:
            db.session.rollback()
            flash('Error creating batch', 'error')
        return redirect(url_for('index'))
    return render_template('create_batch.html')

@app.route('/professors',methods=['GET','POST'])
def manage_professors():
    classrooms = Building.query.all()
    if request.method == "POST":
        if 'file' in request.files:
            file = request.files["file"]
            if file.filename != '':
                try:
                    stream = TextIOWrapper(file.stream)
                    csv_input = csv.reader(stream)
                    next(csv_input)
                    
                    success_count = 0
                    duplicate_count = 0
                    invalid_count = 0
                    
                    for row in csv_input:
                        if len(row) < 2 or not row[0].strip() or not row[1].strip():
                            invalid_count += 1
                            continue
                        
                        name = row[0].strip()
                        email = row[1].strip()

                        
                        if Professor.query.filter(
                            (Professor.name == name) | (Professor.email == email)
                        ).first():
                            duplicate_count += 1
                            continue
                        
                        # Add new professor
                        new_professor = Professor(name=name, email=email)
                        db.session.add(new_professor)
                        success_count += 1

                    db.session.commit()
                    flash_message = f"Successfully added {success_count} professors"
                    if duplicate_count:
                        flash_message += f", skipped {duplicate_count} duplicates"
                    if invalid_count:
                        flash_message += f", ignored {invalid_count} invalid rows"
                    flash(flash_message, 'success' if success_count else 'warning')

                except Exception as e:
                    db.session.rollback()
                    flash(f'Error processing file: {str(e)}', 'error')
        else:
            name = request.form.get("name")
           # email = request.form.get("email")
            priority1=request.form.get("professor_id1")
            priority2=request.form.get("professor_id2")
            priority3=request.form.get("professor_id3")
            #flash(f'{name} + {email}')
            if name:
                new_professor = Professor(name=name,priority_classroom_1=priority1,priority_classroom_2=priority2,priority_classroom_3=priority3)
                db.session.add(new_professor)
                try:
                    db.session.commit()
                    flash('Professor added successfully', 'success')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error adding professor: {str(e)}', 'error')

        return redirect(url_for("manage_professors"))
    professors = Professor.query.all()
    return render_template('professors.html', professors=professors, classrooms=classrooms)
    """print("All classrooms in database:")
    for c in classrooms:
        print(f"ID: {c.id}, Name: {c.name}, Capacity: {c.capacity}")"""

@app.route('/classroom_type',methods=['GET','POST'])
def manage_classrooms_type():
    if request.method=="POST":
        name = request.form.get("name")
        if name:
            new_classroom_type = Building(name=name)
            db.session.add(new_classroom_type)
            try:
                db.session.commit()
                flash('Classroom Type added successfully', 'success')
            except:
                db.session.rollback()
                flash('Error adding classroom', 'error')

        return redirect(url_for("manage_classrooms_type"))

    classrooms = Building.query.all()
    """print("All classrooms in database:")
    for c in classrooms:
        print(f"ID: {c.id}, Name: {c.name}, Capacity: {c.capacity}")"""
    return render_template('classrooms_type.html', classrooms=classrooms)

@app.route('/classrooms/<int:idd>', methods=['GET', 'POST'])
def manage_classrooms(idd):
    # print(idd)
    if request.method == "POST":
        if 'file' in request.files:
            file = request.files["file"]
            if file.filename != '':
                try:
                    stream = TextIOWrapper(file.stream)
                    csv_input = csv.reader(stream)
                    next(csv_input)
                    
                    success_count = 0
                    duplicate_count = 0
                    invalid_count = 0
                    
                    for row in csv_input:
                        if len(row) < 2 or not row[0].strip() or not row[1].strip():
                            invalid_count += 1
                            continue
                        
                        name = row[0].strip()
                        try:
                            capacity = int(row[1])
                        except ValueError:
                            invalid_count += 1
                            continue
                        
                        if Classroom.query.filter_by(name=name).first():
                            duplicate_count += 1
                            continue
                        
                        new_classroom = Classroom(name=name, capacity=capacity)
                        db.session.add(new_classroom)
                        success_count += 1
                    
                    db.session.commit()
                    flash_message = f"Successfully added {success_count} classrooms"
                    if duplicate_count:
                        flash_message += f", skipped {duplicate_count} duplicates"
                    if invalid_count:
                        flash_message += f", ignored {invalid_count} invalid rows"
                    flash(flash_message, 'success' if success_count else 'warning')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error processing file: {str(e)}', 'error')
        else:
            name = request.form.get("name")
            capacity = request.form.get("capacity")
            if name and capacity:
                new_classroom = Classroom(name=name, capacity=capacity,building_id=idd)
                db.session.add(new_classroom)
                try:
                    db.session.commit()
                    flash('Classroom added successfully', 'success')
                except:
                    db.session.rollback()
                    flash('Error adding classroom', 'error')

        return redirect(url_for("manage_classrooms",idd=idd))
    
    classrooms = Classroom.query.filter_by(building_id=idd).all()

    """print("All classrooms in database:")
    for c in classrooms:
        print(f"ID: {c.id}, Name: {c.name}, Capacity: {c.capacity}")"""
    return render_template('classrooms.html', classrooms=classrooms, idd=idd)

@app.route('/delete_classroom/<int:id>', methods=['POST', 'GET'])
def delete_classroom(id):
    classroom = Classroom.query.get_or_404(id)  # find by ID or show 404
    idd=classroom.building_id
    try:
        db.session.delete(classroom)   # delete it
        db.session.commit()            # save changes
        flash(f'Classroom "{classroom.name}" deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting classroom: {str(e)}', 'error')
    
    return redirect(url_for('manage_classrooms',idd=idd))

@app.route('/delete_lab/<int:id>', methods=['POST', 'GET'])
def delete_lab(id):
    lab = Lab.query.get_or_404(id)  # find by ID or show 404
    try:
        db.session.delete(lab)   # delete it
        db.session.commit()            # save changes
        flash(f'Classroom "{lab.name}" deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting classroom: {str(e)}', 'error')
    
    return redirect(url_for('manage_labs'))

@app.route('/delete_professor/<int:id>', methods=['POST', 'GET'])
def delete_professor(id):
    professor = Professor.query.get_or_404(id)  # find by ID or show 404
    try:
        db.session.delete(professor)   # delete it
        db.session.commit()            # save changes
        flash(f'Classroom "{professor.name}" deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting classroom: {str(e)}', 'error')
    
    return redirect(url_for('manage_professors'))

@app.route('/labs', methods=['GET', 'POST'])
def manage_labs():
    if request.method == 'POST':
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                try:
                    stream = TextIOWrapper(file.stream)
                    csv_input = csv.reader(stream)
                    next(csv_input)
                    
                    success_count = 0
                    duplicate_count = 0
                    invalid_count = 0
                    
                    for row in csv_input:
                        if len(row) < 2 or not row[0].strip() or not row[1].strip():
                            invalid_count += 1
                            continue
                        
                        name = row[0].strip()
                        try:
                            capacity = int(row[1])
                            if capacity <= 0:
                                invalid_count += 1
                                continue
                                
                            if Lab.query.filter_by(name=name).first():
                                duplicate_count += 1
                                continue
                                
                            new_lab = Lab(name=name, capacity=capacity)
                            db.session.add(new_lab)
                            success_count += 1
                        except ValueError:
                            invalid_count += 1
                            continue
                            
                    db.session.commit()
                    flash(f'Successfully added {success_count} labs. {duplicate_count} duplicates skipped. {invalid_count} invalid rows ignored.', 
                          'success' if success_count else 'warning')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error processing CSV: {str(e)}', 'error')
        else:
            lab_name = request.form.get('lab_name')
            lab_capacity = request.form.get('lab_capacity')
            
            if lab_name and lab_capacity:
                try:
                    capacity = int(lab_capacity)
                    if capacity <= 0:
                        flash('Capacity must be positive', 'error')
                    elif Lab.query.filter_by(name=lab_name).first():
                        flash('Lab already exists', 'error')
                    else:
                        new_lab = Lab(name=lab_name, capacity=capacity)
                        db.session.add(new_lab)
                        db.session.commit()
                        flash('Lab added successfully', 'success')
                except ValueError:
                    flash('Invalid capacity value', 'error')
                except Exception as e:
                    db.session.rollback()
                    flash(f'Error adding lab: {str(e)}', 'error')
                    
        return redirect(url_for('manage_labs'))
    
    labs = Lab.query.order_by(Lab.name).all()
    return render_template('labs.html', labs=labs)

@app.route('/delete_batch/<int:id>', methods=['POST', 'GET'])
def delete_batch(id):
    batch = Batch.query.get_or_404(id)   # Find batch by ID or show 404
    try:
        db.session.delete(batch)         # Delete the batch
        db.session.commit()              # Save changes
        flash(f'Batch "{batch.name}" deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()            # Undo changes if error occurs
        flash(f'Error deleting batch: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/batch/<int:batch_id>', methods=['GET', 'POST'])
def manage_batch(batch_id):
    professors = Professor.query.all()
    labs = Lab.query.all() 
    batch = Batch.query.get_or_404(batch_id)
    courses = Course.query.filter_by(batch_id=batch_id).all()

    if request.method == 'POST':
        course_name = request.form['course_name']
        credits = int(request.form['credits'])
        professor_id = request.form.get('professor_id')
        lab_professor_id=request.form.get('professor_id_lab')
        is_lab = 'is_lab' in request.form
        priority = 'priority' in request.form
        #priority_type = request.form.get('priority_type')  # Get the priority type
        priority_shift='priority_shift' in request.form
        #priority_shift_type=request.form.get('priority_shift_type')
        priority_day='priority_day' in request.form
        #priority_day_type=request.form.get('priority_day_type')
        avoid_day = request.form.get('avoid_day')  # Get the selected day to avoid
        lab_classroom_id1 = request.form.get('lab_classroom_id1') if is_lab else None
        lab_classroom_id2 = request.form.get('lab_classroom_id2') if is_lab else None
        lab_classroom_id3 = request.form.get('lab_classroom_id3') if is_lab else None


        if avoid_day:
            avoid_day = int(avoid_day)

        if course_name and credits and professor_id:
            new_course = Course(
                name=course_name,
                credits=int(credits),
                professor_id=int(professor_id),
                is_lab=is_lab,
                priority=priority,
                avoid_day=avoid_day,
                priority_morning=priority_day,
                batch_id=batch_id,
                priority_evening=priority_shift,
                lab_professor_id=lab_professor_id,
                lab_id1=int(lab_classroom_id1) if lab_classroom_id1 else None,
                lab_id2=int(lab_classroom_id2) if lab_classroom_id2 else None,
                lab_id3=int(lab_classroom_id3) if lab_classroom_id3 else None
            )
            try:
                db.session.add(new_course)
                db.session.commit()
                flash('Course added successfully', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error adding course: {str(e)}', 'error')
        else:
            flash('Please fill in all required fields', 'warning')
        courses = Course.query.filter_by(batch_id=batch_id).all()
        #return redirect(url_for('manage_batch'))
    #courses = Course.query.all()
    # else:
    #     print("\n--- Courses for Batch:", batch.name, "---")
    #     for course in courses:
    #         print(f"Course ID: {course.id}, Name: {course.name}, Credits: {course.credits}, Professor ID: {course.professor_id}, Is Lab: {course.is_lab}")
    #     print("--- End of List ---\n")
    return render_template('manage_batch.html', professors=professors, classrooms=labs,batch=batch,courses=courses)

@app.route('/edit_course/<int:course_id>', methods=['GET', 'POST'])
def edit_course(course_id):
    course = Course.query.get_or_404(course_id)
    professors = Professor.query.all()
    labs = Lab.query.all()

    if request.method == 'POST':
        course.priority_shift='priority_shift' in request.form
        #priority_shift_type=request.form.get('priority_shift_type')
        course.priority_day='priority_day' in request.form
        #priority_day_type=request.form.get('priority_day_type')
        lab_classroom_id = request.form.get('lab_classroom_id')
        if course.is_lab:
            course.lab_id = int(lab_classroom_id) if lab_classroom_id else None
        else:
            course.lab_id = None
        #course.lab_id = request.form.get('lab_classroom_id') if lab_classroom_id else None
        # Update fields from form
        course.name = request.form['course_name']
        course.credits = int(request.form['credits'])
        course.professor_id = int(request.form['professor_id'])
        course.is_lab = 'is_lab' in request.form
        course.priority = 'priority' in request.form
        dd=request.form.get('avoid_day')
        if(dd):
            course.avoid_day = int(dd)

        # Only set lab_classroom_id if course is lab
        if course.is_lab:
            lab_classroom_id = request.form.get('lab_classroom_id')
            course.lab_id = int(lab_classroom_id) if lab_classroom_id else None
        else:
            course.lab_id = None

        try:
            db.session.commit()
            flash("Course updated successfully!", "success")
            return redirect(url_for('manage_batch', batch_id=course.batch_id))
        except Exception as e:
            db.session.rollback()
            flash(f"Error updating course: {str(e)}", "error")

    return render_template('edit_course.html', 
                           course=course, 
                           professors=professors, 
                           classrooms=labs)

@app.route('/delete_course/<int:course_id>', methods=['POST'])
def delete_course(course_id):
    course = Course.query.get_or_404(course_id)
    try:
        db.session.delete(course)
        db.session.commit()
        flash(f"Course '{course.name}' deleted successfully!", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting course: {str(e)}", "error")

    # Redirect back to the batch page that the course belonged to
    return redirect(url_for('manage_batch', batch_id=course.batch_id))
 
@app.route('/professor_timetable',methods=['GET'])
def professor_timetale():
    professors = Professor.query.all()
    return render_template('timetable_professor.html',professors=professors)

@app.route('/batch_timetable',methods=['GET'])
def batches_timetale():
    batches = Batch.query.all()
    return render_template('timetable_batch.html',batches=batches)

@app.route('/classroom_timetable',methods=['GET'])
def classroom_timetale():
    classrooms = Classroom.query.all()
    return render_template('timetable_classroom.html',classrooms=classrooms)

@app.route('/lab_timetable',methods=['GET'])
def lab_timetale():
    labs = Lab.query.all()
    return render_template('timetable_lab.html',labs=labs)

@app.route('/timetable',methods=['GET','POST'])
def get_timetable():
    courses=Course.query.all()
    professors=Professor.query.all()
    courses_with_lab = Course.query.filter_by(is_lab=True).all()
    course_data = []
    for c in courses:
        hours = c.credits if not c.is_lab else c.credits - 1
        course_data.append({
            "id": c.id,
            "name": c.name,
            "credits": c.credits,
            "is_lab": c.is_lab,
            "priority":c.priority,
            "priority_morning":c.priority_morning,
            "priority_evening":c.priority_evening,
            "avoid_day":c.avoid_day,
            "professor_id":c.professor_id,
            "lab_professor_id":c.lab_professor_id,
            "lab_id1":c.lab_id1,
            "lab_id2":c.lab_id2,
            "lab_id3":c.lab_id3,
            "batch_id":c.batch_id,
            "hours": hours
        })
    
    priority_morning_courses = [c for c in course_data if c["priority"] and c["priority_morning"]]

    priority_evening_courses = [c for c in course_data if c["priority"] and c["priority_evening"]]

    only_priority=[c for c in course_data if c["priority"] and ((not c["priority_evening"] and not c["priority_morning"]) or (c["priority_evening"] and c["priority_morning"]))]

    morning_only = [c for c in course_data if not c["priority"] and c["priority_morning"]]

    evening_only = [c for c in course_data if not c["priority"] and c["priority_evening"]]

    no_priority=[c for c in course_data if not c["priority"] and ((not c["priority_evening"] and not c["priority_morning"]) or (c["priority_evening"] and c["priority_morning"]))]

    if request.method == 'POST':
        db.session.query(Schedule).delete()
        db.session.commit()

        for course in courses_with_lab:
            batch = Batch.query.filter(Batch.id == course.batch_id).first()
            morning_labp1 = []
            evening_labp1 = []
            morning_labp2 = []
            evening_labp2 = []
            morning_labp3 = []
            evening_labp3 = []
            other=[]

            for day in range(5):
                if day == course.avoid_day:
                    continue 
                for slot in range(4):
                    if slot != 4 :
                        if is_slot_available_lab_priority1(course, day, slot,batch) and is_slot_available_lab_priority1(course, day, slot + 1,batch):
                            morning_labp1.append((day, slot))
                            break
            
            for day in range(5):
                if day == course.avoid_day:
                    continue 
                for slot in range(6,8):
                    if is_slot_available_lab_priority1(course, day, slot,batch) and is_slot_available_lab_priority1(course, day, slot + 1,batch):
                        evening_labp1.append((day, slot))
                        break
            
            for day in range(5):
                if day == course.avoid_day:
                    continue 
                for slot in range(4):
                    if slot != 4 :
                        if is_slot_available_lab_priority2(course, day, slot,batch) and is_slot_available_lab_priority2(course, day, slot + 1,batch):
                            morning_labp2.append((day, slot))
                            break
            
            for day in range(5):
                    if day == course.avoid_day:
                        continue 
                    for slot in range(6,8):
                        if is_slot_available_lab_priority2(course, day, slot,batch) and is_slot_available_lab_priority2(course, day, slot + 1,batch):
                            evening_labp2.append((day, slot))
                            break
            
            for day in range(5):
                if day == course.avoid_day:
                    continue 
                for slot in range(4):
                    if slot != 4 :
                        if is_slot_available_lab_priority3(course, day, slot,batch) and is_slot_available_lab_priority3(course, day, slot + 1,batch):
                            morning_labp3.append((day, slot))
                            break
            
            for day in range(5):
                    if day == course.avoid_day:
                        continue 
                    for slot in range(6,8):
                        if is_slot_available_lab_priority3(course, day, slot,batch) and is_slot_available_lab_priority3(course, day, slot + 1,batch):
                            evening_labp3.append((day, slot))
                            break
            
            for day in range(5): 
                for slot in range(8): 
                    if slot != 4 and slot!=5:
                        if is_slot_available_lab(course, day, slot,batch) and is_slot_available_lab(course, day, slot + 1,batch):
                            other.append((day, slot))

            day = None
            start_slot = None
            lab_assigned=None
            if evening_labp1:
                day, start_slot = random.choice(evening_labp1)
                lab_assigned=course.lab_id1
            elif morning_labp1:
                day,start_slot = random.choice(morning_labp1)
                lab_assigned=course.lab_id1
            elif evening_labp2:
                day,start_slot = random.choice(evening_labp2)
                lab_assigned=course.lab_id2
            elif morning_labp2:
                day,start_slot = random.choice(morning_labp2)
                lab_assigned=course.lab_id2
            elif evening_labp3:
                day,start_slot = random.choice(evening_labp3)
                lab_assigned=course.lab_id3
            elif morning_labp3:
                day,start_slot = random.choice(morning_labp3)
                lab_assigned=course.lab_id3
            elif other:
                day,start_slot=random.choice(other)
                lab_assigned=find_available_lab(day,start_slot,-1, batch)
            else:
                print(f"No available slots for course {course.name}")
                continue  # Skip this iteration if no slots available
            for offset in range(2):
                new_schedule = Schedule(
                    batch_id=course.batch_id,
                    course_id=course.id,
                    professor_id=course.lab_professor_id,
                    lab_id=lab_assigned,
                    day=day,
                    slot=start_slot + offset,
                    classroom_id= None
                )
                db.session.add(new_schedule)
            try:
                db.session.commit()
                flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
            except:
                db.session.rollback()
                flash('Error scheduling priority course (2-hour consecutive)', 'error')

        for course in priority_morning_courses:
            batch = Batch.query.filter(Batch.id == course["batch_id"]).first()
            specific_professor = Professor.query.filter(Professor.id == course["professor_id"]).first()
            priority_priority1_slots=[]
            priority_priority2_slots=[]
            priority_priority3_slots=[]
            priority_other_slots=[]

            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(5):  # Check up to slot 7 for consecutive slots
                    if slot != 4 and slot !=5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_1,batch):
                            priority_priority1_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_2,batch):
                            priority_priority2_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_3,batch):
                            priority_priority3_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,-1,batch) and is_slot_available(course, day, slot+1,-1,batch):
                            priority_other_slots.append((day,slot))
                            break

            days_done=[]

            while course["hours"]>1 and ( priority_priority1_slots or priority_priority2_slots or priority_priority3_slots or priority_other_slots):
                    day = None
                    start_slot = None
                    
                    if priority_priority1_slots:
                        day, start_slot = random.choice(priority_priority1_slots)
                        priority_priority1_slots.remove((day, start_slot))
                    elif priority_priority2_slots:
                        day,start_slot = random.choice(priority_priority2_slots)
                        priority_priority2_slots.remove((day, start_slot))
                    elif priority_priority3_slots:
                        day,start_slot = random.choice(priority_priority3_slots)
                        priority_priority3_slots.remove((day, start_slot))
                    elif priority_other_slots:
                        day,start_slot = random.choice(priority_other_slots)
                        priority_other_slots.remove((day, start_slot))
                    else:
                        print(f"No available slots for course {course['name']}")
                        continue  # Skip this iteration if no slots available
                    classroom1 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_1,batch)
                    classroom2 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_2,batch)
                    classroom3 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_3,batch)
                    last=find_available_classroom(day,slot,batch)

                    if day in days_done:
                        continue

                    days_done.append(day)
                    decided_classroom=None
                    if classroom1:
                        decided_classroom=classroom1
                    elif classroom2:
                        decided_classroom=classroom2
                    elif classroom3:
                        decided_classroom=classroom3
                    else:
                        decided_classroom=last
                    


                    course["hours"]-=2
                    for offset in range(2):
                        new_schedule = Schedule(
                            batch_id=course["batch_id"],
                            course_id=course["id"],
                            professor_id=course["professor_id"],
                            day=day,
                            slot=start_slot + offset,
                            classroom_id= decided_classroom.id
                        )
                        db.session.add(new_schedule)
                    try:
                        db.session.commit()
                        flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                    except:
                        db.session.rollback()
                        flash('Error scheduling priority course (2-hour consecutive)', 'error')

            morning_priority1_slots=[]
            morning_priority2_slots=[]
            morning_priority3_slots=[]
            morning_other_slots=[]

            for day in range(5):
                    if day == course["avoid_day"] or day in days_done:
                        continue 
                    for slot in range(5,9):  # Check up to slot 7 for consecutive slots
                        if slot !=5:
                            if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                                morning_priority1_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                                morning_priority2_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                                morning_priority3_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,-1,batch):
                                morning_other_slots.append((day,slot))
            
            evening_priority1_slots=[]
            evening_priority2_slots=[]
            evening_priority3_slots=[]
            evening_other_slots=[]

            for day in range(5):
                    if day == course["avoid_day"] or day in days_done:
                        continue 
                    for slot in range(5):  # Check up to slot 7 for consecutive slots
                        if slot !=5:
                            if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                                evening_priority1_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                                evening_priority2_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                                evening_priority3_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,-1,batch):
                                evening_other_slots.append((day,slot))

            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]

            for day in range(5):
                for slot in range(9):  # Check up to slot 7 for consecutive slots
                    if slot !=5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_other_slots or last_priority1_slots or last_priority2_slots or last_priority3_slots or morning_priority1_slots or morning_priority2_slots or morning_priority3_slots or morning_other_slots or evening_other_slots or evening_priority1_slots or evening_priority2_slots or evening_priority3_slots):
                day = None
                start_slot = None
                
                if evening_priority1_slots:
                    day, start_slot = random.choice(evening_priority1_slots)
                    evening_priority1_slots.remove((day, start_slot))
                elif evening_priority2_slots:
                    day,start_slot = random.choice(evening_priority2_slots)
                    evening_priority2_slots.remove((day, start_slot))
                elif evening_priority3_slots:
                    day,start_slot = random.choice(evening_priority3_slots)
                    evening_priority3_slots.remove((day, start_slot))
                elif evening_other_slots:
                    day,start_slot = random.choice(evening_other_slots)
                    evening_other_slots.remove((day, start_slot))
                elif morning_priority1_slots:
                    day,start_slot=random.choice(morning_priority1_slots)
                    morning_priority1_slots.remove((day,start_slot))
                elif morning_priority2_slots:
                    day,start_slot = random.choice(morning_priority2_slots)
                    morning_priority2_slots.remove((day, start_slot))
                elif morning_priority3_slots:
                    day,start_slot = random.choice(morning_priority3_slots)
                    morning_priority3_slots.remove((day, start_slot))
                elif morning_other_slots:
                    day,start_slot = random.choice(morning_other_slots)
                    morning_other_slots.remove((day, start_slot))
                elif last_priority1_slots:
                    day,start_slot=random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day,start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                decided_classroom=None
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                if day in days_done:
                    continue
                days_done.append(day)
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                elif last:
                    decided_classroom=last
                else:
                    continue
                
                course["hours"]-=1
                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot + offset,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]

            for day in range(5):
                for slot in range(9):
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_priority1_slots or last_priority2_slots or last_priority3_slots or last_other_slots):
                day = None
                start_slot = None
                if last_priority1_slots:
                    day, start_slot = random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day, start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

        for course in priority_evening_courses:
            batch = Batch.query.filter(Batch.id == course["batch_id"]).first()
            specific_professor = Professor.query.filter(Professor.id == course["professor_id"]).first()
            priority_priority1_slots=[]
            priority_priority2_slots=[]
            priority_priority3_slots=[]
            priority_other_slots=[]

            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(5,8):
                    if slot != 4 and slot !=5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_1,batch):
                            priority_priority1_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_2,batch):
                            priority_priority2_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_3,batch):
                            priority_priority3_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,-1,batch) and is_slot_available(course, day, slot+1,-1,batch):
                            priority_other_slots.append((day,slot))
                            break

            days_done=[]

            while course["hours"]>1 and ( priority_priority1_slots or priority_priority2_slots or priority_priority3_slots or priority_other_slots):
                    day = None
                    start_slot = None
                    if priority_priority1_slots:
                        day, start_slot = random.choice(priority_priority1_slots)
                        priority_priority1_slots.remove((day, start_slot))
                    elif priority_priority2_slots:
                        day,start_slot = random.choice(priority_priority2_slots)
                        priority_priority2_slots.remove((day, start_slot))
                    elif priority_priority3_slots:
                        day,start_slot = random.choice(priority_priority3_slots)
                        priority_priority3_slots.remove((day, start_slot))
                    elif priority_other_slots:
                        day,start_slot = random.choice(priority_other_slots)
                        priority_other_slots.remove((day, start_slot))
                    else:
                        print(f"No available slots for course {course['name']}")
                        continue  # Skip this iteration if no slots available
                    classroom1 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_1,batch)
                    classroom2 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_2,batch)
                    classroom3 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_3,batch)
                    last=find_available_classroom(day,slot,batch)

                    if day in days_done:
                        continue
                    days_done.append(day)
                    decided_classroom=None
                    if classroom1:
                        decided_classroom=classroom1
                    elif classroom2:
                        decided_classroom=classroom2
                    elif classroom3:
                        decided_classroom=classroom3
                    else:
                        decided_classroom=last
                    
                    course["hours"]-=2
                    for offset in range(2):
                        new_schedule = Schedule(
                            batch_id=course["batch_id"],
                            course_id=course["id"],
                            professor_id=course["professor_id"],
                            day=day,
                            slot=start_slot + offset,
                            classroom_id= decided_classroom.id
                        )
                        db.session.add(new_schedule)
                    try:
                        db.session.commit()
                        flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                    except:
                        db.session.rollback()
                        flash('Error scheduling priority course (2-hour consecutive)', 'error')

            morning_priority1_slots=[]
            morning_priority2_slots=[]
            morning_priority3_slots=[]
            morning_other_slots=[]

            for day in range(5):
                    if day == course["avoid_day"] or day in days_done:
                        continue 
                    for slot in range(5):  # Check up to slot 7 for consecutive slots
                        if slot !=5:
                            if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                                morning_priority1_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                                morning_priority2_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                                morning_priority3_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,-1,batch):
                                morning_other_slots.append((day,slot))
            
            evening_priority1_slots=[]
            evening_priority2_slots=[]
            evening_priority3_slots=[]
            evening_other_slots=[]

            for day in range(5):
                    if day == course["avoid_day"] or day in days_done:
                        continue 
                    for slot in range(5,9):  # Check up to slot 7 for consecutive slots
                        if slot !=5:
                            if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                                evening_priority1_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                                evening_priority2_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                                evening_priority3_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,-1,batch):
                                evening_other_slots.append((day,slot))

            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]

            for day in range(5):
                for slot in range(9):  # Check up to slot 7 for consecutive slots
                    if slot !=5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_other_slots or last_priority1_slots or last_priority2_slots or last_priority3_slots or morning_priority1_slots or morning_priority2_slots or morning_priority3_slots or morning_other_slots or evening_other_slots or evening_priority1_slots or evening_priority2_slots or evening_priority3_slots):
                day = None
                start_slot = None
                if evening_priority1_slots:
                    day, start_slot = random.choice(evening_priority1_slots)
                    evening_priority1_slots.remove((day, start_slot))
                elif evening_priority2_slots:
                    day,start_slot = random.choice(evening_priority2_slots)
                    evening_priority2_slots.remove((day, start_slot))
                elif evening_priority3_slots:
                    day,start_slot = random.choice(evening_priority3_slots)
                    evening_priority3_slots.remove((day, start_slot))
                elif evening_other_slots:
                    day,start_slot = random.choice(evening_other_slots)
                    evening_other_slots.remove((day, start_slot))
                elif morning_priority1_slots:
                    day,start_slot=random.choice(morning_priority1_slots)
                    morning_priority1_slots.remove((day,start_slot))
                elif morning_priority2_slots:
                    day,start_slot = random.choice(morning_priority2_slots)
                    morning_priority2_slots.remove((day, start_slot))
                elif morning_priority3_slots:
                    day,start_slot = random.choice(morning_priority3_slots)
                    morning_priority3_slots.remove((day, start_slot))
                elif morning_other_slots:
                    day,start_slot = random.choice(morning_other_slots)
                    morning_other_slots.remove((day, start_slot))
                elif last_priority1_slots:
                    day,start_slot=random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day,start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available

                if day in days_done:
                    continue
                days_done.append(day)
                decided_classroom=None
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                elif last:
                    decided_classroom=last
                else:
                    continue
                
                course["hours"]-=1
                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot + offset,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]

            for day in range(5):
                for slot in range(9):
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_priority1_slots or last_priority2_slots or last_priority3_slots or last_other_slots):
                day = None
                start_slot = None
                if last_priority1_slots:
                    day, start_slot = random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day, start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

        for course in only_priority:
            batch = Batch.query.filter(Batch.id == course["batch_id"]).first()
            specific_professor = Professor.query.filter(Professor.id == course["professor_id"]).first()

            priority_priority1_slots=[]
            priority_priority2_slots=[]
            priority_priority3_slots=[]
            priority_other_slots=[]
            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(8):  # Check up to slot 7 for consecutive slots
                    if slot != 5 and slot !=4:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_1,batch):
                            priority_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_2,batch):
                            priority_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch) and is_slot_available(course, day, slot+1,specific_professor.priority_classroom_3,batch):
                            priority_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch) and is_slot_available(course, day, slot+1,-1,batch):
                            priority_other_slots.append((day,slot))

            days_done=[]

            while course["hours"]>1 and (priority_priority1_slots or priority_priority2_slots or priority_priority3_slots or priority_other_slots):
                day = None
                start_slot = None
                if priority_priority1_slots:
                    day, start_slot = random.choice(priority_priority1_slots)
                    priority_priority1_slots.remove((day, start_slot))
                elif priority_priority2_slots:
                    day,start_slot = random.choice(priority_priority2_slots)
                    priority_priority2_slots.remove((day, start_slot))
                elif priority_priority3_slots:
                    day,start_slot = random.choice(priority_priority3_slots)
                    priority_priority3_slots.remove((day, start_slot))
                elif priority_other_slots:
                    day,start_slot = random.choice(priority_other_slots)
                    priority_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available

                if day in days_done:
                    continue
                days_done.append(day)

                decided_classroom=None
                classroom1 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom(day,slot,batch)
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                
                course["hours"]-=2
                for offset in range(2):
                    new_schedule = Schedule(
                        batch_id=course["batch_id"],
                        course_id=course["id"],
                        professor_id=course["professor_id"],
                        day=day,
                        slot=start_slot + offset,
                        classroom_id= decided_classroom.id
                    )
                    db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

            priority1_slots=[]
            priority2_slots=[]
            priority3_slots=[]
            other_slots=[]

            for day in range(5):
                    if day == course["avoid_day"] or day in days_done:
                        continue 
                    for slot in range(9):  # Check up to slot 7 for consecutive slots
                        if slot !=5:
                            if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                                priority1_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                                priority2_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                                priority3_slots.append((day, slot))
                            elif is_slot_available(course, day, slot,-1,batch):
                                other_slots.append((day,slot))
                

            while course["hours"]>0 and (priority1_slots or priority2_slots or priority3_slots or other_slots):
                day = None
                start_slot = None
                if priority1_slots:
                    day, start_slot = random.choice(priority1_slots)
                    priority1_slots.remove((day, start_slot))
                elif priority2_slots:
                    day,start_slot = random.choice(priority2_slots)
                    priority2_slots.remove((day, start_slot))
                elif priority3_slots:
                    day,start_slot = random.choice(priority3_slots)
                    priority3_slots.remove((day, start_slot))
                elif other_slots:
                    day,start_slot = random.choice(other_slots)
                    other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                if day in days_done:
                    continue
                days_done.append(day)
                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]

            for day in range(5):
                for slot in range(9):
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_priority1_slots or last_priority2_slots or last_priority3_slots or last_other_slots):
                day = None
                start_slot = None
                if last_priority1_slots:
                    day, start_slot = random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day, start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

        for course in morning_only:
            batch = Batch.query.filter(Batch.id == course["batch_id"]).first()
            priority1_slots=[]
            priority2_slots=[]
            priority3_slots=[]
            other_slots=[]
            specific_professor = Professor.query.filter(Professor.id == course["professor_id"]).first()


            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(5):  # Check up to slot 7 for consecutive slots
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            other_slots.append((day,slot))

            morning_priority1_slots=[]
            morning_priority2_slots=[]
            morning_priority3_slots=[]
            morning_other_slots=[]

            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(5,9):  # Check up to slot 7 for consecutive slots
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            morning_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            morning_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            morning_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            morning_other_slots.append((day,slot))

            days_done=[]
            while course["hours"]>0 and (priority1_slots or priority2_slots or priority3_slots or morning_priority1_slots or morning_priority2_slots or morning_priority3_slots or other_slots or morning_other_slots):
                day = None
                start_slot = None
                if priority1_slots:
                    day, start_slot = random.choice(priority1_slots)
                    priority1_slots.remove((day, start_slot))
                elif priority2_slots:
                    day,start_slot = random.choice(priority2_slots)
                    priority2_slots.remove((day, start_slot))
                elif priority3_slots:
                    day,start_slot = random.choice(priority3_slots)
                    priority3_slots.remove((day, start_slot))
                elif other_slots:
                    day,start_slot = random.choice(other_slots)
                    other_slots.remove((day, start_slot))
                elif morning_priority1_slots:
                    day,start_slot = random.choice(morning_priority1_slots)
                    morning_priority1_slots.remove((day, start_slot))
                elif morning_priority2_slots:
                    day,start_slot = random.choice(morning_priority2_slots)
                    morning_priority2_slots.remove((day, start_slot))
                elif morning_priority3_slots:
                    day,start_slot = random.choice(morning_priority3_slots)
                    morning_priority3_slots.remove((day, start_slot))
                elif morning_other_slots:
                    day,start_slot = random.choice(morning_other_slots)
                    morning_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)
                        
                if day in days_done:
                    continue
                days_done.append(day)
                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')
            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]

            for day in range(5):
                for slot in range(9):
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_priority1_slots or last_priority2_slots or last_priority3_slots or last_other_slots):
                day = None
                start_slot = None
                if last_priority1_slots:
                    day, start_slot = random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day, start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

        for course in evening_only:
            batch = Batch.query.filter(Batch.id == course["batch_id"]).first()
            priority1_slots=[]
            priority2_slots=[]
            priority3_slots=[]
            other_slots=[]
            specific_professor = Professor.query.filter(Professor.id == course["professor_id"]).first()

            days_done=[]
            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(5,9):  # Check up to slot 7 for consecutive slots
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            other_slots.append((day,slot))

            morning_priority1_slots=[]
            morning_priority2_slots=[]
            morning_priority3_slots=[]
            morning_other_slots=[]

            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(5):  # Check up to slot 7 for consecutive slots
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            morning_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            morning_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            morning_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            morning_other_slots.append((day,slot))

            while course["hours"]>0 and (priority1_slots or priority2_slots or priority3_slots or morning_priority1_slots or morning_priority2_slots or morning_priority3_slots or other_slots or morning_other_slots):
                day = None
                start_slot = None
                if priority1_slots:
                    day, start_slot = random.choice(priority1_slots)
                    priority1_slots.remove((day, start_slot))
                elif priority2_slots:
                    day,start_slot = random.choice(priority2_slots)
                    priority2_slots.remove((day, start_slot))
                elif priority3_slots:
                    day,start_slot = random.choice(priority3_slots)
                    priority3_slots.remove((day, start_slot))
                elif other_slots:
                    day,start_slot = random.choice(other_slots)
                    other_slots.remove((day, start_slot))
                elif morning_priority1_slots:
                    day,start_slot = random.choice(morning_priority1_slots)
                    morning_priority1_slots.remove((day, start_slot))
                elif morning_priority2_slots:
                    day,start_slot = random.choice(morning_priority2_slots)
                    morning_priority2_slots.remove((day, start_slot))
                elif morning_priority3_slots:
                    day,start_slot = random.choice(morning_priority3_slots)
                    morning_priority3_slots.remove((day, start_slot))
                elif morning_other_slots:
                    day,start_slot = random.choice(morning_other_slots)
                    morning_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                if day in days_done:
                    continue
                days_done.append(day)
                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')


            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]

            for day in range(5):
                for slot in range(9):
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_priority1_slots or last_priority2_slots or last_priority3_slots or last_other_slots):
                day = None
                start_slot = None
                if last_priority1_slots:
                    day, start_slot = random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day, start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1

                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

        for course in no_priority:
            batch = Batch.query.filter(Batch.id == course["batch_id"]).first()
            priority1_slots=[]
            priority2_slots=[]
            priority3_slots=[]
            other_slots=[]
            specific_professor = Professor.query.filter(Professor.id == course["professor_id"]).first()
            for day in range(5):
                if day == course["avoid_day"]:
                    continue 
                for slot in range(9):  # Check up to slot 7 for consecutive slots
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            priority1_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            priority2_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            priority3_slots.append((day, slot))
                            break
                        elif is_slot_available(course, day, slot,-1,batch):
                            other_slots.append((day,slot))
                            break

            days_done=[]

            while course["hours"]>0 and (priority1_slots or priority2_slots or priority3_slots or other_slots):
                day = None
                start_slot = None
                if priority1_slots:
                    day, start_slot = random.choice(priority1_slots)
                    priority1_slots.remove((day, start_slot))
                elif priority2_slots:
                    day,start_slot = random.choice(priority2_slots)
                    priority2_slots.remove((day, start_slot))
                elif priority3_slots:
                    day,start_slot = random.choice(priority3_slots)
                    priority3_slots.remove((day, start_slot))
                elif other_slots:
                    day,start_slot = random.choice(other_slots)
                    other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                
                if day in days_done:
                    continue
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1
                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

            last_priority1_slots=[]
            last_priority2_slots=[]
            last_priority3_slots=[]
            last_other_slots=[]
            specific_professor = Professor.query.filter(Professor.id == course["professor_id"]).first()
            for day in range(5):
                for slot in range(9):  # Check up to slot 7 for consecutive slots
                    if slot != 5:
                        if is_slot_available(course, day, slot,specific_professor.priority_classroom_1,batch):
                            last_priority1_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_2,batch):
                            last_priority2_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,specific_professor.priority_classroom_3,batch):
                            last_priority3_slots.append((day, slot))
                        elif is_slot_available(course, day, slot,-1,batch):
                            last_other_slots.append((day,slot))

            while course["hours"]>0 and (last_priority1_slots or last_priority2_slots or last_priority3_slots or last_other_slots):
                day = None
                start_slot = None
                if last_priority1_slots:
                    day, start_slot = random.choice(last_priority1_slots)
                    last_priority1_slots.remove((day, start_slot))
                elif last_priority2_slots:
                    day,start_slot = random.choice(last_priority2_slots)
                    last_priority2_slots.remove((day, start_slot))
                elif last_priority3_slots:
                    day,start_slot = random.choice(last_priority3_slots)
                    last_priority3_slots.remove((day, start_slot))
                elif last_other_slots:
                    day,start_slot = random.choice(last_other_slots)
                    last_other_slots.remove((day, start_slot))
                else:
                    print(f"No available slots for course {course['name']}")
                    continue  # Skip this iteration if no slots available
                        
                classroom1 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_1,batch)
                classroom2 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_2,batch)
                classroom3 = find_available_classroom_with_priorityroom_onehour(day, start_slot,specific_professor.priority_classroom_3,batch)
                last=find_available_classroom_onehour(day,slot,batch)

                decided_classroom=None
                if classroom1:
                    decided_classroom=classroom1
                elif classroom2:
                    decided_classroom=classroom2
                elif classroom3:
                    decided_classroom=classroom3
                else:
                    decided_classroom=last
                course["hours"]-=1
                new_schedule = Schedule(
                    batch_id=course["batch_id"],
                    course_id=course["id"],
                    professor_id=course["professor_id"],
                    day=day,
                    slot=start_slot,
                    classroom_id= decided_classroom.id
                )
                db.session.add(new_schedule)
                try:
                    db.session.commit()
                    flash('Priority course scheduled successfully (2-hour consecutive)', 'success')
                except:
                    db.session.rollback()
                    flash('Error scheduling priority course (2-hour consecutive)', 'error')

    return render_template('timetable_home.html')

@app.route('/specific_batch_timetable/<int:id>', methods=['GET'])
def specific_batch_timetable(id):
    flash("HELLO")
    schedules = Schedule.query.filter_by(batch_id=id).all()
    timetable = [["-" for _ in range(9)] for _ in range(5)]
    
    # Set lunch break for all days at slot 4 (12:00 PM - 1:00 PM)
    # for day in range(5):
    #timetable[2][4] = "Lunch"

    print(len(schedules))
    for schedule in schedules:
        course = Course.query.get(schedule.course_id)
        professor = Professor.query.get(schedule.professor_id)
        classroom= Classroom.query.get(schedule.classroom_id)
        lab = Lab.query.get(schedule.lab_id)
        # Construct the timetable entry dynamically
        entry = f"{course.name}({professor.name})"
        if lab is not None:
            entry += f", {lab.name}"
        if classroom is not None:
            entry += f" {classroom.name}"
        # Assign the constructed entry to the timetable
        timetable[schedule.day][schedule.slot] = entry
    return render_template('show_timetable_batch.html', timetable=timetable)

@app.route('/specific_professor_timetable/<int:id>', methods=['GET'])
def specific_professor_timetable(id):
    flash("HELLO")
    schedules = Schedule.query.filter_by(professor_id=id).all()
    timetable = [["-" for _ in range(9)] for _ in range(5)]

    print(len(schedules))
    for schedule in schedules:
        course = Course.query.get(schedule.course_id)
        professor = Professor.query.get(schedule.professor_id)
        batch= Batch.query.get(schedule.batch_id)
        classroom= Classroom.query.get(schedule.classroom_id)
        lab = Lab.query.get(schedule.lab_id)
        # Construct the timetable entry dynamically
        entry = f"{course.name}({batch.name})"
        if lab is not None:
            entry += f", {lab.name}"
        if classroom is not None:
            entry += f" {classroom.name}"
        # Assign the constructed entry to the timetable
        timetable[schedule.day][schedule.slot] = entry
    return render_template('show_timetable_professor.html', timetable=timetable)

@app.route('/specific_classroom_timetable/<int:id>', methods=['GET'])
def specific_classroom_timetable(id):
    flash("HELLO")
    schedules = Schedule.query.filter_by(classroom_id=id).all()
    timetable = [["-" for _ in range(9)] for _ in range(5)]

    print(len(schedules))
    for schedule in schedules:
        course = Course.query.get(schedule.course_id)
        professor = Professor.query.get(schedule.professor_id)
        batch= Batch.query.get(schedule.batch_id)
        classroom= Classroom.query.get(schedule.classroom_id)
        lab = Lab.query.get(schedule.lab_id)
        # Construct the timetable entry dynamically
        entry = f"{course.name}({batch.name}{professor.name})"
        if lab is not None:
            entry += f", {lab.name}"
        if classroom is not None:
            entry += f" {classroom.name}"
        # Assign the constructed entry to the timetable
        timetable[schedule.day][schedule.slot] = entry
    return render_template('show_timetable_classroom.html', timetable=timetable)

@app.route('/specific_lab_timetable/<int:id>', methods=['GET'])
def specific_lab_timetable(id):
    flash("HELLO")
    schedules = Schedule.query.filter_by(lab_id=id).all()
    timetable = [["-" for _ in range(9)] for _ in range(5)]

    print(len(schedules))
    for schedule in schedules:
        course = Course.query.get(schedule.course_id)
        professor = Professor.query.get(schedule.professor_id)
        batch= Batch.query.get(schedule.batch_id)
        classroom= Classroom.query.get(schedule.classroom_id)
        lab = Lab.query.get(schedule.lab_id)
        # Construct the timetable entry dynamically
        entry = f"{course.name}({batch.name}-{professor.name})"
        # Assign the constructed entry to the timetable
        timetable[schedule.day][schedule.slot] = entry
    return render_template('show_timetable_lab.html', timetable=timetable)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)