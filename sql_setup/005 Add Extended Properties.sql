EXEC sys.sp_addextendedproperty 

        @name  = 'AGENTS.md', 

        @value = N' 
# AdventureWorks2025 NL2SQL Data Source Instructions (AGENTS.md) 

## Entities 
For the following entities, use the specified tables only
### Sales
- SalesOrder -> Sales.SalesOrderHeader 
- SalesOrderLine -> Sales.SalesOrderDetail 

### Product
- Product -> Production.Product 

### Loyalty Programme
- LoyaltyCard -> Loyalty.LoyaltyCard
- LoyaltyPoints -> Loyalty.PointsLedger

### Inventory
- Inventory -> Production.ProductInventory
- Product -> Production.Product
- Summary of inventory is the sum of Quantity on hand across all inventory records for a product.

## Lookups for values - get values from extended properties on these columns
- Sales.SalesOrderHeaderStatus 

## Join Rules (safe paths) 

- Sales.SalesOrder.CustomerID = Sales.Customer.CustomerID 
- Sales.SalesOrder.SalesOrderID = Sales.SalesOrderDetail.SalesOrderID 
- Loyalty.LoyaltyCard.CustomerID = Sales.Customer.CustomerID
- Production.Product.ProductID = Sales.SalesOrderDetail.ProductID
- Production.Product.ProductID = Production.ProductInventory.ProductID

## Vector columns
- Use Production.Product.ProductEmbedding for vector queries on product descriptions.

## Metrics 

- OrderValue := SUM(SalesOrderHeader.TotalDue) 
- UnitsBought    := SUM(SalesOrderDetail.OrderQty) 
- LoyaltyPointsEarned := SUM(PointsLedger.PointsChange)
- LoyaltyPointsBalance := PointsLedger.Running_Total
- StockLevel := SUM(Production.ProductInventory.Quantity)
- PointsLedger.Running_Total is the balance of loyalty points after each transaction, while PointsLedger.PointsChange is the change in points value for that transaction
- A basket is an entry in the sales headers table, so count of sales headers is the number of baskets.


'; 