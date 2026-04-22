-- Add a new column to the Product table to store the concatenated product name, model name, and description. 
--This will allow for easier searching and display of product information without needing to join multiple tables every time.
-- The concatenated column will be used for generating vector embeddings for semantic search, enabling more intelligent search capabilities based on product information.
-- It is not possible to create an embedding using multiple columns, so we need to combine the relevant text into a single column before generating the embedding.

-- Step 1: Add a NameModelDescription column
ALTER TABLE [Production].[Product]
ADD [NameModelDescription] VARCHAR(450);


-- Step 2: Update with product descriptions (294 rows will be updated)
WITH CombinedProductInfo AS (
    SELECT p.ProductID, CONCAT_WS('',p.Name, pm.Name,pd.Description) AS ConcatenatedInfo
    FROM Production.Product p
    LEFT JOIN Production.ProductModel pm ON p.ProductModelID = pm.ProductModelID
    LEFT JOIN Production.ProductModelProductDescriptionCulture pmpdc 
    ON pm.ProductModelID = pmpdc.ProductModelID 
    AND pmpdc.CultureID = 'en'
    LEFT JOIN Production.ProductDescription pd 
    ON pmpdc.ProductDescriptionID = pd.ProductDescriptionID
) 
UPDATE Production.Product
SET NameModelDescription = ConcatenatedInfo FROM CombinedProductInfo
WHERE Production.Product.ProductID = CombinedProductInfo.ProductID;

--Step 3: Add a vector column, ProductEmbedding
ALTER TABLE [Production].[Product]
ADD [ProductEmbedding] VECTOR(1536) NULL;

--Step 4: Create master key
CREATE MASTER KEY
ENCRYPTION BY PASSWORD = '';
GO

--Step 5: Create a database scoped credential for Azure OpenAI authentication
CREATE DATABASE SCOPED CREDENTIAL []
    WITH IDENTITY = 'HTTPEndpointHeaders', secret = '{"api-key":""}';
GO

--Step 6: Grant permissions to create external model (required for AI_GENERATE_EMBEDDINGS function)
GRANT CREATE EXTERNAL MODEL TO [];

--Step 7: Enable external REST endpoints in the database to allow calling Azure OpenAI from SQL Server. This is required for the AI_GENERATE_EMBEDDINGS function to work.
EXECUTE sp_configure 'external rest endpoint enabled', 1;
RECONFIGURE WITH OVERRIDE;

--Step 8: Add the external model for generating embeddings using Azure OpenAI
CREATE EXTERNAL MODEL TextEmbedding3Small
AUTHORIZATION "EUROPE\fenyan"
WITH (
      LOCATION = 'https://sqlbitsfoundry.cognitiveservices.azure.com/openai/deployments/text-embedding-3-small/embeddings?api-version=2024-02-01',
      API_FORMAT = 'Azure OpenAI',
      MODEL_TYPE = EMBEDDINGS,
      MODEL = 'text-embedding-3-small',
      CREDENTIAL = []     
);

--Step 9: Add the embeddings for the NameModelDescription column to the vector column
UPDATE Production.Product
SET ProductEmbedding = CAST(
    AI_GENERATE_EMBEDDINGS(NameModelDescription USE MODEL TextEmbedding3Small) 
    AS VECTOR(1536)
)


-- NOTE: A vector index can be added but isn't necessary. Without an index, the database will perform a full scan of the Product table for vector similarity searches, which is still feasible for smaller datasets.
-- Vector index creation is a preview feature that needs to be enabled
