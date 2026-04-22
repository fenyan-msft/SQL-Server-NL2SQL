use master;

-- Step 1: Create SQL Login at server level
CREATE LOGIN [cleverstoreagent001] 
WITH PASSWORD = '***', -- Something Secure and a Password and 1-3 plus an exclamation mark
     CHECK_POLICY = ON,
     CHECK_EXPIRATION = OFF;
GO

-- Step 2: Switch to AdventureWorks2022 database and create user
USE AdventureWorks2022;
GO

CREATE USER [cleverstoreagent001] FOR LOGIN [cleverstoreagent001];
GO

-- Step 3: Grant read-only access
ALTER ROLE db_datareader ADD MEMBER [cleverstoreagent001];
GO

-- Step 4: Explicitly deny write and schema modification permissions
DENY INSERT, UPDATE, DELETE, ALTER TO [cleverstoreagent001];
GO

GRANT SELECT ON SCHEMA::dbo TO cleverstoreagent001;
GO

GRANT SELECT ON SCHEMA::Production TO cleverstoreagent001;
GO

GRANT SELECT ON SCHEMA::Sales TO cleverstoreagent001;
GO

GRANT SELECT ON SCHEMA::Person TO cleverstoreagent001;
