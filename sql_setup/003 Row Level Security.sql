use [AdventureWorks2022]

-- Row level security

-- Step 1: Create a login and user (if needed)
CREATE LOGIN cleverstoreagent001 WITH PASSWORD = '[Enter Password Here]';
GO

CREATE USER cleverstoreagent001 FOR LOGIN cleverstoreagent001;
GO

GRANT SELECT ON SCHEMA::dbo TO cleverstoreagent001;
GO


-- Step 2: Create a schema for security objects
CREATE SCHEMA Security;
GO

-- Step 3: Create a security predicate function
-- This example filters rows based on a PersonID column
CREATE FUNCTION Security.fn_SecurityPredicate(@PersonID AS INT)
    RETURNS TABLE
WITH SCHEMABINDING
AS
    RETURN SELECT 1 AS result
    WHERE (@PersonID = SESSION_CONTEXT(N'PersonID') AND SESSION_CONTEXT(N'PersonID') IS NOT NULL)
       OR IS_MEMBER('db_owner') = 1;
GO

-- Step 4: Create a security policy on a specific table
-- Replace 'YourTableName' with your actual table name
-- DROP SECURITY POLICY Security.UserDataPolicy
CREATE SECURITY POLICY Security.UserDataPolicy
    ADD FILTER PREDICATE Security.fn_SecurityPredicate(PersonID)
        ON Sales.Customer
    WITH (STATE = ON);
GO


-- This version looks up the CustomerID in sales.customer and checks if the PersonID for that customer matches the session context, or if the user is a db_owner. This allows you to filter based on a related table.
CREATE FUNCTION Security.fn_SecurityLinkedPredicate(@CustomerID AS INT)
    RETURNS TABLE
WITH SCHEMABINDING
AS
		RETURN SELECT 1 AS result
		WHERE EXISTS (SELECT 1 FROM sales.customer 
			WHERE ((PersonID = SESSION_CONTEXT(N'PersonID') AND SESSION_CONTEXT(N'PersonID') IS NOT NULL)
					OR IS_MEMBER('db_owner') = 1) AND CustomerID = @CustomerID) ;
GO

-- Now link Customer ID to session context
-- DROP SECURITY POLICY Security.UserDataPolicySalesOrderHeaderCustomerID;
CREATE SECURITY POLICY Security.UserDataPolicySalesOrderHeaderCustomerID
    ADD FILTER PREDICATE Security.fn_SecurityLinkedPredicate(CustomerID)
        ON [Sales].[SalesOrderHeader]
    WITH (STATE = ON);
GO



-- This version links to sales.customer filtering on session conext for PersonID, but it also links to salesorderheader to filter salesorderdetail based on the customerid in salesorderheader. This allows you to filter salesorderdetail based on the personid in sales.customer via the link through salesorderheader.
CREATE FUNCTION Security.fn_SecuritySalesOrderDetail(@SalesOrderID AS INT)
    RETURNS TABLE
WITH SCHEMABINDING
AS
		RETURN SELECT 1 AS result
		WHERE EXISTS (SELECT 1 FROM sales.customer sc join SALES.SalesOrderHeader sh on sc.CustomerID = sh.CustomerID
			WHERE ((sc.PersonID = SESSION_CONTEXT(N'PersonID') AND SESSION_CONTEXT(N'PersonID') IS NOT NULL)
					OR IS_MEMBER('db_owner') = 1) AND sh.SalesOrderID = @SalesOrderID) ;
GO


-- Now link Customer ID to session context
-- DROP SECURITY POLICY Security.UserDataPolicySalesOrderDetailSalesOrderID;
CREATE SECURITY POLICY Security.UserDataPolicySalesOrderDetailSalesOrderID
    ADD FILTER PREDICATE Security.fn_SecuritySalesOrderDetail(SalesOrderID)
        ON [Sales].[SalesOrderDetail]
    WITH (STATE = ON);
GO
-- *** NOTE YOU CANNOT IMPLICITLY USE RLS TO JOIN AS THIS DESTROYS PERFORMANCE

/*************************************************************

	Test Code - if you run this logged on as a user you should see a limited data set returned
	If you log on as admin, it will return the full data set

	*************************************************************/

-- Step 5: Set session context for the user
-- This would typically be done in application code or stored procedure
EXEC sp_set_session_context @key = N'PersonID', @value = 13332;
-- IMPORTANT: MAKE IT AN INT IN PRODUCTION OR NULL

SELECT * FROM Sales.Customer; -- This will return rows where PersonID = ? or if the user is a db_owner
-- Simple filter on PersonID

SELECT * FROM [Sales].[SalesOrderHeader]
-- Linked filter on CustomerID that looks up PersonID in sales.customer and checks against session context. Returns rows where the CustomerID matches a PersonID in sales.customer that matches the session context, or if the user is a db_owner.

-- Connect as the cleverstoreagent001 user and run the above SELECT statements to see the row-level security in action. You should only see rows where the PersonID matches the session context value (13332 in this case) or if you are a db_owner, you will see all rows.

SELECT * FROM Sales.SalesOrderDetail

-- These won't work until you put the Loyalty schema in place and link it to the customerid in sales.customer, but once you do that you can use the same pattern to filter those tables based on the personid in sales.customer via the customerid link.
SELECT * FROM Loyalty.LoyaltyCard
SELECT * FROM Loyalty.pointsledger

