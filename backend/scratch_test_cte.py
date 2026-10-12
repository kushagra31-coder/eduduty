import sqlite3

con = sqlite3.connect(":memory:")
con.execute("CREATE TABLE ai_attendance_summary (class_name TEXT, roll_number TEXT, student_name TEXT)")
con.execute("INSERT INTO ai_attendance_summary VALUES ('CI-1', 'R101', 'Alice'), ('Cyber-3', 'R201', 'Bob')")

# Test 1: CTE shadowing table name with main schema prefix
sql1 = """
WITH ai_attendance_summary AS (
    SELECT * FROM main.ai_attendance_summary WHERE class_name IN ('CI-1')
)
SELECT * FROM ai_attendance_summary
"""
res1 = con.execute(sql1).fetchall()
print("Test 1 Result:", res1)

# Test 2: UNION attempt
sql2 = """
WITH ai_attendance_summary AS (
    SELECT * FROM main.ai_attendance_summary WHERE class_name IN ('CI-1')
)
SELECT * FROM ai_attendance_summary WHERE class_name = 'CI-1'
UNION
SELECT * FROM ai_attendance_summary WHERE class_name = 'Cyber-3'
"""
res2 = con.execute(sql2).fetchall()
print("Test 2 Result (UNION):", res2)

# Test 3: Subquery attempt
sql3 = """
WITH ai_attendance_summary AS (
    SELECT * FROM main.ai_attendance_summary WHERE class_name IN ('CI-1')
)
SELECT * FROM ai_attendance_summary WHERE roll_number IN (
    SELECT roll_number FROM ai_attendance_summary WHERE class_name = 'Cyber-3'
)
"""
res3 = con.execute(sql3).fetchall()
print("Test 3 Result (Subquery):", res3)

# Test 4: Omitted filter / SELECT *
sql4 = """
WITH ai_attendance_summary AS (
    SELECT * FROM main.ai_attendance_summary WHERE class_name IN ('CI-1')
)
SELECT COUNT(*) FROM ai_attendance_summary
"""
res4 = con.execute(sql4).fetchall()
print("Test 4 Result (Count):", res4)
