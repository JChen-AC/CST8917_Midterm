import azure.functions as func            # Azure Functions SDK
import azure.durable_functions as df      # Durable Functions extension
from azure.data.tables import TableServiceClient, TableClient  # Table Storage SDK
import logging                            # Python built-in logging
import json                               # Python built-in JSON handling
import os                                 # Python built-in for environment variables

from pypdf import PDFReader

# =============================================================================
# CREATE THE DURABLE FUNCTION APP
# =============================================================================

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# =============================================================================
# TABLE STORAGE HELPER
# =============================================================================

TABLE_NAME = "PDFAnalysisResults"

def get_table_client():
    """Helper function to initialize Azure Table Storage client."""
    connection_string = os.environ["AzureWebJobsStorage"]
    table_service = TableServiceClient.from_connection_string(connection_string)
    table_service.create_table_if_not_exists(TABLE_NAME)
    return table_service.get_table_client(TABLE_NAME)

# =============================================================================
# 1. CLIENT FUNCTION (Blob Trigger - The Entry Point)
# =============================================================================
# Automatically fires when a document hits the 'pdfs' container
@app.blob_trigger(
    arg_name="myblob",
    path="pdfs/{name}",
    connection="AzureWebJobsStorage"
)
@app.durable_client_input(client_name="client")
async def pdf_blob_trigger(myblob: func.InputStream, client: df.DurableOrchestrationClient):
    # Extract blob path details and payload metrics
    blob_name = myblob.name
    blob_bytes = myblob.read()
    blob_size_kb = round(len(blob_bytes) / 1024, 2)

    logging.info(f"[Client] New PDF file detected: {blob_name} ({blob_size_kb} KB)")

    # Serializing bytes into an integer list because Durable Functions inputs must be JSON stable
    input_data = {
        "blob_name": blob_name,
        "blob_bytes": list(blob_bytes),
        "blob_size_kb": blob_size_kb
    }

    # Pass control off to your workflow director
    instance_id = await client.start_new(
        "pdf_orchestrator",
        client_input=input_data
    )

    logging.info(f"[Client] Orchestration workflow successfully initiated. ID: {instance_id}")


# =============================================================================
# 2. ORCHESTRATOR FUNCTION (Hybrid Management Workflow)
# =============================================================================
@app.orchestration_trigger(context_name="context")
def pdf_orchestrator(context: df.DurableOrchestrationContext):
    input_data = context.get_input()
    logging.info(f"[Orchestrator] Active state tracking for file: {input_data['blob_name']}")

    # -------------------------------------------------------------------------
    # PHASE A: FAN-OUT 
    # -------------------------------------------------------------------------
    # Launching execution tasks concurrently without separate 'yield' expressions
    analysis_tasks = [
        context.call_activity("extract_text", input_data),
        context.call_activity("extract_metadata", input_data),
        context.call_activity("analyze_statistics", input_data),
        context.call_activity("detect_sensitive_data", input_data),
    ]

    # PHASE B: FAN-IN (Execution blocking aggregation)
    # The workflow pauses here until all 4 background analysis activities resolve safely
    results = yield context.task_all(analysis_tasks)
    logging.info("[Orchestrator] Fan-In completed. Moving to sequential chaining context.")

    # -------------------------------------------------------------------------
    # PHASE C: CHAINING - Generate report from combined results
    # -------------------------------------------------------------------------
    report_input = {
        "blob_name": input_data["blob_name"],
        "text_content": results[0],
        "metadata": results[1],
        "statistics": results[2],
        "sensitive_data": results[3],
    }

    # Step 1: Structural generation
    report = yield context.call_activity("combine_results", report_input)

    # Step 2: Storage persistence
    record = yield context.call_activity("store_report", report)

    return record


# =============================================================================
# ACTIVITY: (Placeholders for testing orchestration)
# =============================================================================

## ACTIVITY 1: Extract Text from PDF 
@app.activity_trigger(input_name="inputData")
def extract_text(inputData: dict) -> dict:

    reader = PDFReader(inputData)
    
    

    return {"text": "Stubbed out plain text representation."}

@app.activity_trigger(input_name="inputData")
def extract_metadata(inputData: dict) -> dict:
    reader = PDFReader(inputData)
    meta = reader.metadata
    metadata = {}    
    metadata['Author'] = meta.author 
    metadata['Title'] = meta.title
    metadata['Creation Date '] = meta.creation_date
    metadata['Modification Date '] = meta.modification_date
    # REFERENCE :https://pypdf.readthedocs.io/en/stable/user/metadata.html
    # AI Disclosure, AI was used to research ways to extract text from pdf and comparing the capbailities of the libraries (wihtout code generation, just gave summary of ool and links to documentation)

    #return {"author": "Stubbed Author", "title": "Stubbed Title"}
    return metadata

@app.activity_trigger(input_name="inputData")
def analyze_statistics(inputData: dict) -> dict:
    return {"page_count": 5, "word_count": 1200}

@app.activity_trigger(input_name="inputData")
def detect_sensitive_data(inputData: dict) -> dict:
    return {"emails": ["test@algonquinlive.com"], "phone_numbers": []}

@app.activity_trigger(input_name="reportData")
def combine_results(reportData: dict) -> dict:
    return {"status": "mock_compiled", "payload": reportData}

@app.activity_trigger(input_name="report")
def store_report(report: dict) -> dict:
    return {"status": "mock_saved", "row_key": "12345"}


# =============================================================================
# 3. HTTP RETRIEVAL ENDPOINT 
# =============================================================================
@app.route(route="results/{blob_name}")
def get_pdf_results(req: func.HttpRequest) -> func.HttpResponse:
    blob_name = req.route_params.get("blob_name")
    logging.info(f"[HTTP Endpoint] Query requested for resource target: {blob_name}")
    
    # Placeholder 
    placeholder = {
        "status": "infrastructure_active",
        "message": f"Looking up analysis entities for target asset {blob_name}."
    }
    return func.HttpResponse(json.dumps(placeholder), mimetype="application/json", status_code=200)