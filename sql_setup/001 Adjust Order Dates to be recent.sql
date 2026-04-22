-- Adjust transactions to be up to date

DECLARE @OrderOffset INT = DATEDIFF(DAY,(SELECT MAX(DueDate) FROM sales.SalesOrderHeader), GETDATE())

UPDATE sales.SalesOrderHeader
	SET OrderDate = DATEADD(DAY, @OrderOffset, OrderDate),
		DueDate = DATEADD(DAY, @OrderOffset, DueDate),
		ShipDate = DATEADD(DAY, @OrderOffset, ShipDate);

SELECT MAXORDERDATE = MAX(ORDERDATE), MAXDUEDATE = MAX(DUEDATE), MAXSHIPDATE = MAX(SHIPDATE) FROM sales.SalesOrderHeader

