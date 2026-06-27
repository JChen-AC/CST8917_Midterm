from datetime import datetime 
import uuid

import azure.functions as func            # Azure Functions SDK
import azure.durable_functions as df      # Durable Functions extension
from azure.data.tables import TableServiceClient, TableClient  # Table Storage SDK
import base64                              # Python built-in for encoding bytes
import logging                            # Python built-in logging
import json                               # Python built-in JSON handling
import os                                 # Python built-in for environment variables

from pypdf import PdfReader
import io 

from activities.analyze_statistics import bp as analyze_statistics_bp
from activities.detect_sensitive_data import bp as detect_sensitive_data_bp

# =============================================================================
# CREATE THE DURABLE FUNCTION APP
# =============================================================================

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)
app.register_functions(analyze_statistics_bp)
app.register_functions(detect_sensitive_data_bp)

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
        "blob_bytes_b64": base64.b64encode(blob_bytes).decode("ascii"),
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

    # AI was used to debug the input for PdfReader, as it was throwing an error. The issue was that it wanted either the exact file path or the file bytes. And claude suggested the file bytes as those are already give in inputData
    blob_bytes = bytes(inputData["blob_bytes"])
    reader = PdfReader(io.BytesIO(blob_bytes))
        
    num_pgs = len(reader.pages)

    page_data = []

    for p in range(num_pgs):
        page = reader.pages[p]
        text = page.extract_text()
        page_data.append(text)
        print(text)
    # need to know how to output it, as 1 large pand or creatu sculltpture /specific format
    
    # reference used : https://www.geeksforgeeks.org/python/extract-text-from-pdf-file-using-python/
    # AI WAS ALSO USED TO HELP DEBUG AND SETUP THE LOCAL TESTING ENVIRONMENT AS THERE WAS SOME VERSION ISSUES AND SETTING UP THE LOCAL CONTAINER 
    
    return {"text": "Stubbed out plain text representation."}

@app.activity_trigger(input_name="inputData")
def extract_metadata(inputData: dict) -> dict:

    # AI was used to debug the input for PdfReader, as it was throwing an error. The issue was that it wanted either the exact file path or the file bytes. And claude suggested the file bytes as those are already give in inputData
    blob_bytes = bytes(inputData["blob_bytes"])
    reader = PdfReader(io.BytesIO(blob_bytes))


    meta = reader.metadata
    metadata = {}    
    metadata['Author'] = meta.author 
    metadata['Title'] = meta.title
    metadata['Creation Date '] = meta.creation_date.isoformat()
    metadata['Modification Date '] = meta.modification_date.isoformat()
    # REFERENCE :https://pypdf.readthedocs.io/en/stable/user/metadata.html
    # AI Disclosure, AI was used to research ways to extract text from pdf and comparing the capbailities of the libraries (wihtout code generation, just gave summary of ool and links to documentation)

    #return {"author": "Stubbed Author", "title": "Stubbed Title"}
    print(metadata)
    return metadata

@app.activity_trigger(input_name="reportData")
def combine_results(reportData: dict) -> dict:
    logging.info("[Activity] Combining results into a structured report.")
    blob_name = reportData.get("blob_name")
    file_name = blob_name.split("/")[-1] if blob_name else "processedpdf.pdf"
    report = {
        "id": str(uuid.uuid4()),
        "file_name": file_name,
        "blob_name": blob_name,
        "analyzedAt": datetime.utcnow().isoformat(),
        "analyses": {
            "text_content": reportData["text_content"],
            "metadata": reportData["metadata"],
            "statistics": reportData["statistics"],
            "sensitive_data": reportData["sensitive_data"],
        },
        "summary": {
            "total_pages": reportData["statistics"].get("page_count", 0),
            "total_words": reportData["statistics"].get("word_count", 0),
            "average_words_per_page": reportData["statistics"].get("avg_words_per_page", 0.0),
            "total_emails": len(reportData["sensitive_data"].get("emails", [])),
            "total_phone_numbers": len(reportData["sensitive_data"].get("phone_numbers", [])),
            "total_urls": len(reportData["sensitive_data"].get("urls", [])),
            "total_dates": len(reportData["sensitive_data"].get("dates", [])),
        }
    }

    return report

@app.activity_trigger(input_name="report")
def store_report(report: dict) -> dict:
    logging.info("[Activity] Storing report in Azure Table Storage.")
    try:
        table_client = get_table_client()
        row_key = report["id"]
        report_entity = {
            "PartitionKey": "PDFReports",
            "RowKey": row_key,
            "file_name": report["file_name"],
            "blob_name": report["blob_name"],
            "analyzedAt": report["analyzedAt"],
            "summary": json.dumps(report["summary"]),
            "text_content": json.dumps(report["analyses"]["text_content"]),
            "metadata": json.dumps(report["analyses"]["metadata"]),
            "statistics": json.dumps(report["analyses"]["statistics"]),
            "sensitive_data": json.dumps(report["analyses"]["sensitive_data"])
        }
        table_client.upsert_entity(report_entity)

        logging.info(f"[Activity] Report stored successfully with RowKey: {row_key}")
        return {
            "id": report["id"],
            "file_name": report["file_name"],
            "status": "report_stored", 
            "analyzedAt": report["analyzedAt"],
            "summary": report["summary"]
            }
    
    except Exception as e:
        logging.error(f"[Activity] Failed to store report: {e}")
        return {
            "id": report.get("id", "unknown"),
            "file_name": report.get("file_name", "unknown"),
            "status": "error",
            "message": str(e)
        }



# =============================================================================
# 3. HTTP RETRIEVAL ENDPOINT 
# =============================================================================
@app.route(route="results/{id}")
def get_pdf_results(req: func.HttpRequest) -> func.HttpResponse:
    ##blob_name = req.route_params.get("blob_name")
    ##logging.info(f"[HTTP Endpoint] Query requested for resource target: {blob_name}")
    try:
        table_client = get_table_client()
        result_id = req.route_params.get("id")
        if result_id:
            try:
                entity = table_client.get_entity(partition_key="PDFReports", row_key=result_id)
                return func.HttpResponse(
                    json.dumps(entity),
                    mimetype="application/json",
                    status_code=200
                )
            except Exception as e:
                logging.error(f"[HTTP Endpoint] Failed to retrieve entity: {e}")
                return func.HttpResponse(
                    json.dumps({"status": "error", "message": "Entity not found."}),
                    mimetype="application/json",
                    status_code=404
                )
    except Exception as e:
        logging.error(f"[HTTP Endpoint] Failed to initialize Table Storage client: {e}")
        return func.HttpResponse(
            json.dumps({"status": "error", "message": "Failed to connect to Table Storage."}),
            mimetype="application/json",
            status_code=500
        )

    # Placeholder 
    placeholder = {
        "status": "infrastructure_active",
        "message": f"Looking up analysis entities for target asset {result_id}."
    }
    return func.HttpResponse(json.dumps(placeholder), mimetype="application/json", status_code=200)