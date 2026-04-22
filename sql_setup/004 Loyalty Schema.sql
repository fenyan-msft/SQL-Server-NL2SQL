CREATE SCHEMA Loyalty;
GO

GRANT SELECT ON SCHEMA::Loyalty TO cleverstoreagent001;
GO


CREATE TABLE Loyalty.LoyaltyCard
(
	LoyaltyCardID INT IDENTITY (1,1) NOT NULL,
	CardNumber VARCHAR(20) NOT NULL,
	PersonID INT NOT NULL,
	IssueDate DATETIME NOT NULL,
	Status VARCHAR(20) NOT NULL
)


/****** Object:  Index [PK_TransactionHistory_TransactionID]    Script Date: 27/03/2026 10:39:50 ******/
ALTER TABLE Loyalty.LoyaltyCard ADD  CONSTRAINT [PK_LoyaltyCard_LoyaltyCardID] PRIMARY KEY CLUSTERED 
(
	[LoyaltyCardID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, SORT_IN_TEMPDB = OFF, IGNORE_DUP_KEY = OFF, ONLINE = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
GO

EXEC sys.sp_addextendedproperty 
@name=N'MS_Description', 
@value=N'Primary key (clustered) constraint' , 
@level0type=N'SCHEMA',
@level0name=N'Loyalty', 
@level1type=N'TABLE',
@level1name=N'LoyaltyCard', 
@level2type=N'CONSTRAINT',
@level2name=N'PK_LoyaltyCard_LoyaltyCardID'

GO


CREATE TABLE Loyalty.PointsLedger
(
	PointsLedgerID INT IDENTITY (1,1) NOT NULL,
	LoyaltyCardID INT NOT NULL,
	TransactionDate DATETIME NOT NULL,
	PointsChange INT NOT NULL,
    Running_Total INT NOT NULL,
	TransactionID INT  NULL,
	MarketingCampaignID INT 
)

/****** Object:  Index [PK_TransactionHistory_TransactionID]    Script Date: 27/03/2026 10:39:50 ******/
ALTER TABLE Loyalty.PointsLedger ADD  CONSTRAINT [PK_PointsLedger_PointsLedgerID] PRIMARY KEY CLUSTERED 
(
	[PointsLedgerID] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, SORT_IN_TEMPDB = OFF, IGNORE_DUP_KEY = OFF, ONLINE = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
GO

EXEC sys.sp_addextendedproperty 
@name=N'MS_Description', 
@value=N'Primary key (clustered) constraint' , 
@level0type=N'SCHEMA',
@level0name=N'Loyalty', 
@level1type=N'TABLE',
@level1name=N'PointsLedger', 
@level2type=N'CONSTRAINT',
@level2name=N'PK_PointsLedger_PointsLedgerID'

GO

-- Not used: Foreign Key on Transaction History
--ALTER TABLE [Loyalty].[PointsLedger]  WITH CHECK ADD  CONSTRAINT [FK_PointsLedger_TransactionHistory_TransactionID] 
--FOREIGN KEY([TransactionID])
--REFERENCES [Production].[TransactionHistory] ([TransactionID])
--GO

--ALTER TABLE [Loyalty].[PointsLedger]  CHECK CONSTRAINT [FK_PointsLedger_TransactionHistory_TransactionID]
--GO

--EXEC sys.sp_addextendedproperty 
--	@name=N'MS_Description', 
--	@value=N'Foreign key constraint referencing TransactionHistory.TransactionID.' , 
--	@level0type=N'SCHEMA',
--	@level0name=N'Loyalty', 
--	@level1type=N'TABLE',
--	@level1name=N'PointsLedger', 
--	@level2type=N'CONSTRAINT',
--	@level2name=N'FK_PointsLedger_TransactionHistory_TransactionID'

--GO


-- Define basic foreign key relationship between PointsLedger and LoyaltyCard. This is not strictly necessary for the RLS to work, but it helps to enforce data integrity and also allows for easier joins in queries.
ALTER TABLE [Loyalty].[PointsLedger]  WITH CHECK ADD  CONSTRAINT [FK_PointsLedger_LoyaltyCard_LoyaltyCardID] 
FOREIGN KEY([LoyaltyCardID])
REFERENCES [Loyalty].[LoyaltyCard] ([LoyaltyCardID])
GO

ALTER TABLE [Loyalty].[PointsLedger]  CHECK CONSTRAINT [FK_PointsLedger_LoyaltyCard_LoyaltyCardID] 
GO


-- Implement RLS for LoyaltyCard 
-- Implement RLS for Points Ledger 

-- Link Customer ID to session context
-- DROP SECURITY POLICY Security.UserDataPolicyLoyaltyCardPersonID;
CREATE SECURITY POLICY Security.UserDataPolicyLoyaltyCardPersonID
    ADD FILTER PREDICATE Security.fn_SecurityPredicate(PersonID)
        ON [loyalty].[LoyaltyCard]
    WITH (STATE = ON);
GO

-- This version looks up the PersonID in sales.customer and checks if the PersonID for that customer matches the session context, or if the user is a db_owner. This allows you to filter based on a related table.
CREATE FUNCTION Security.fn_SecurityLinkedPredicateLoyaltyCardID(@LoyaltyCardID AS INT)
    RETURNS TABLE
WITH SCHEMABINDING
AS
		RETURN SELECT 1 AS result
		WHERE EXISTS (SELECT 1 FROM Loyalty.LoyaltyCard
			WHERE ((PersonID = SESSION_CONTEXT(N'PersonID') AND SESSION_CONTEXT(N'PersonID') IS NOT NULL)
					OR IS_MEMBER('db_owner') = 1) AND LoyaltyCardID = @LoyaltyCardID) ;
GO

CREATE SECURITY POLICY Security.UserDataPolicyPointsLedgerLoyaltyCardID
    ADD FILTER PREDICATE Security.fn_SecurityLinkedPredicateLoyaltyCardID(LoyaltyCardID)
        ON Loyalty.PointsLedger 
    WITH (STATE = ON);
GO



EXEC sys.sp_addextendedproperty 
	@name=N'MS_Description', 
	@value=N'Foreign key constraint referencing LoyaltyCard.LoyaltyCardID.' , 
	@level0type=N'SCHEMA',
	@level0name=N'Loyalty', 
	@level1type=N'TABLE',
	@level1name=N'PointsLedger', 
	@level2type=N'CONSTRAINT',
	@level2name=N'FK_PointsLedger_LoyaltyCard_LoyaltyCardID'

GO


INSERT [Loyalty].[LoyaltyCard]
(
    [CardNumber]
,	[PersonID]
,   [IssueDate]
,   [Status]
)
VALUES
('CARD000001', 13332, '2010-03-05', 'Active'),
('CARD000002', 13531, '2012-03-06', 'Active'),
('CARD000003', 5454, '2014-03-07', 'Expired'),
('CARD000004', 11269, '2012-03-08', 'Active'),
('CARD000005', 11358, '2020-03-09', 'Active');      
GO


declare @id INT = 1;
declare @PersonID int;
declare @IssueDate datetime;

SELECT @PersonID = PersonID, @IssueDate = IssueDate FROM [Loyalty].[LoyaltyCard] WHERE LoyaltyCardID = @id;

WHILE (@@ROWCOUNT > 0)
BEGIN
-- CTE
-- Starts on CARD START DATE
-- Goes up to today
-- Each step, take 2x GUIDS
-- Convert one to a positive int between 0 and 14		-- Days Elapsed
-- Convert one to a random number between -165 and +185	-- Points change
-- If running total - points change is less than 0, set points change to 0 - running total (so that we don't go negative)

;WITH LoyaltyTransactions AS (
    -- Anchor: Initial transaction on March 5, 2020
    SELECT 
        @id AS LoyaltyCardID,
        CAST(@IssueDate AS DATE) AS TransactionDate,
        100 AS Points_change,  -- Initial points balance
        100 AS Running_Total
    
    UNION ALL
    
    -- Recursive: Generate subsequent transactions
    SELECT 
        @id AS LoyaltyCardID,
        DATEADD(DAY, 
            (ABS(CHECKSUM(NEWID())) % 30) + 1,  -- Random 1-30 days between entries
            t.TransactionDate) AS TransactionDate,
        -- Random change adjusted to prevent negative balance
        CASE 
            WHEN t.Running_Total + r.RandomChange < 0 
            THEN -t.Running_Total  -- Maximum deduction to reach 0
            ELSE r.RandomChange
        END AS Points_change,
        -- Calculate new running total (never below 0)
        CASE 
            WHEN t.Running_Total + r.RandomChange < 0 
            THEN 0
            ELSE t.Running_Total + r.RandomChange
        END AS Running_Total
    FROM LoyaltyTransactions t
    CROSS APPLY (
        -- Generate random change between -100 and +250
        SELECT (ABS(CHECKSUM(NEWID())) % 351) - 165 AS RandomChange
    ) r
    WHERE DATEADD(DAY, 1, t.TransactionDate) <= GETDATE()
)
INSERT INTO Loyalty.PointsLedger (LoyaltyCardID, TransactionDate, PointsChange, Running_Total)
SELECT 
    LoyaltyCardID,
    TransactionDate,
    Points_change,
    Running_Total
FROM LoyaltyTransactions
WHERE TransactionDate <= GETDATE()
OPTION (MAXRECURSION 0);

SELECT @ID = @ID + 1;
SELECT @PersonID = PersonID, @IssueDate = IssueDate FROM [Loyalty].[LoyaltyCard] WHERE LoyaltyCardID = @id;
END



