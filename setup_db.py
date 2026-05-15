import psycopg2

try:
    conn = psycopg2.connect(host='localhost', database='postgres', user='postgres', password='postgres')
    conn.set_client_encoding('UTF8')
    conn.autocommit = True
    cur = conn.cursor()
    
    # Create user
    try:
        cur.execute("CREATE USER borsa WITH PASSWORD 'borsa123'")
        print("User 'borsa' created")
    except psycopg2.errors.DuplicateObject:
        print("User 'borsa' already exists")
    
    # Create database
    try:
        cur.execute("CREATE DATABASE borsa OWNER borsa")
        print("Database 'borsa' created")
    except psycopg2.errors.DuplicateDatabase:
        print("Database 'borsa' already exists")
    
    # Grant privileges
    cur.execute("GRANT ALL PRIVILEGES ON DATABASE borsa TO borsa")
    print("Privileges granted")
    
    cur.close()
    conn.close()
    print("Setup complete!")
except Exception as e:
    print("Error:", e)
