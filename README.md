# 🎓 Student Analytics & Performance Dashboard

A Django-based web application designed to track student performance, unit-wise marks, and attendance using multi-sheet Excel workbooks.

## 📊 Required Excel Workbook Structure

To use the dashboard successfully, I have provided a sample template Excel file in this repository. You can refer to it to understand how to structure the Excel sheets and workbook, and what exact column names and data to write inside.

Alternatively, you can directly download the sample template Excel file, upload it into the system, and test how everything works right away!

To use the dashboard successfully, upload a single `.xlsx` master workbook containing these 3 sheets:

1. **Sheet 1 (`Subject_Structure`)**
   * Defines subject rules and maximum marks.
   * **Columns:** `Subject Name`, `Subject Type`, `Total Marks Max`, `Theory Max`, `Practical Max`, `Internal Max`, `Assignment Max`, `Presentation Max`, `Unit 1 Max`, `Unit 2 Max`, `Unit 3 Max`, `Unit 4 Max`.

2. **Sheet 2 (`Student_Marks`)**
   * Tracks individual student scores.
   * **Columns:** `Roll Number`, `Student Name`, `Subject Name`, `Semester`, `Unit 1`, `Unit 2`, `Unit 3`, `Unit 4`, `Practical`, `Internal`, `Assignment`, `Presentation`.

3. **Sheet 3 (`Attendance`)**
   * Tracks lecture and practical attendance records.
   * **Columns:** `Roll Number`, `Student Name`, `Subject Name`, `Semester`, `Theory Attended`, `Theory Total`, `Practical Attended`, `Practical Total`.

## 🗂️ Workbook Organization Options (How to Structure Your Data)
You have complete flexibility in how you provide your Excel data:

* **Option A: Single Master Workbook (Combined)**
  * You can combine students from **all years and semesters** into **one single Excel file**. 
  * The system automatically identifies and categorizes students based on their **Roll Numbers**.

* **Option B: Separate Workbooks (Class-wise)**
  * Alternatively, you can create and upload **separate Excel files** for different academic groups, years, or batches (e.g., separate files for First Year, Second Year, Third Year, or MSc parts).

## 🚀 How to Run Locally
1. Clone the repository and navigate to the project folder.
2. Install dependencies: `pip install -r requirements.txt`
3. Run migrations: `python manage.py migrate`
4. Start the server: `python manage.py runserver`
5. Open your browser and go to `http://127.0.0.1:8000/`.
