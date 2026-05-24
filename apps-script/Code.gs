/**
 * The Garage — document locker backend (Google Apps Script web app)
 * ------------------------------------------------------------------
 * Stores vehicle document scans in Google Drive and keeps a small index
 * in a "DocFiles" tab of your fleet spreadsheet. The static GitHub Pages
 * dashboard talks to this over HTTPS:
 *
 *   GET  ?action=files   -> { ok:true, files:{ "vehicleId|DocType": {url,name,uploadedAt} } }
 *   POST {action:'upload', token, vehicle_id, doc_type, filename, mimeType, dataBase64}
 *        -> saves to Drive, indexes it, writes the link back into the sheet,
 *           returns { ok:true, url, name }
 *   POST {action:'delete', token, vehicle_id, doc_type} -> removes it
 *
 * Cross-origin note: the dashboard sends POSTs as text/plain so the browser
 * makes a "simple" request (no CORS preflight, which Apps Script can't answer).
 *
 * SETUP: see README.md. Set TOKEN below to any random string and put the same
 * value in the dashboard's DOC_API_TOKEN GitHub Actions variable.
 */

// ----------------------------- CONFIG ------------------------------------- //
var TOKEN = "CHANGE_ME_to_a_long_random_string";        // shared secret for uploads
var ROOT_FOLDER_NAME = "Vehicle Documents (The Garage)"; // Drive folder to create/use
var INDEX_SHEET = "DocFiles";                            // tab that indexes uploads
var DATA_SHEET = "";  // leave "" to auto-detect the tab that has a vehicle_id column

// Document type -> the *_file column in your data sheet (for write-back).
var FILE_COLUMNS = {
  "Insurance": "insurance_file",
  "PUC": "puc_file",
  "Registration (RC)": "rc_file",
  "Fitness": "fitness_file",
  "Permit": "permit_file",
  "Road Tax": "road_tax_file"
};

// ----------------------------- ENTRY POINTS ------------------------------- //
function doGet(e) {
  var action = (e && e.parameter && e.parameter.action) || "";
  if (action === "files") return json_({ ok: true, files: readIndex_() });
  return json_({ ok: true, status: "ready" });
}

function doPost(e) {
  try {
    var body = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    if (TOKEN && body.token !== TOKEN) return json_({ ok: false, error: "unauthorized" });

    if (body.action === "delete") return json_(deleteDoc_(body));
    if (body.action === "upload") return json_(uploadDoc_(body));
    return json_({ ok: false, error: "unknown action" });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

// ----------------------------- CORE LOGIC --------------------------------- //
function uploadDoc_(body) {
  var vehicleId = String(body.vehicle_id || "").trim();
  var docType = String(body.doc_type || "").trim();
  if (!vehicleId || !docType || !body.dataBase64) {
    return { ok: false, error: "missing vehicle_id, doc_type or file data" };
  }

  var bytes = Utilities.base64Decode(body.dataBase64);
  var ext = guessExt_(body.filename, body.mimeType);
  var name = docType + " - " + vehicleId + ext;
  var blob = Utilities.newBlob(bytes, body.mimeType || "application/octet-stream", name);

  var folder = getVehicleFolder_(vehicleId);
  var key = vehicleId + "|" + docType;

  // Replace any previous file for this exact paper.
  var existing = findIndexRow_(key);
  if (existing && existing.driveId) { try { DriveApp.getFileById(existing.driveId).setTrashed(true); } catch (e) {} }

  var file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  var url = "https://drive.google.com/file/d/" + file.getId() + "/view";

  upsertIndex_(key, vehicleId, docType, url, name, file.getId());
  writeLinkToDataSheet_(vehicleId, docType, url); // best-effort

  return { ok: true, url: url, name: name };
}

function deleteDoc_(body) {
  var key = String(body.vehicle_id || "") + "|" + String(body.doc_type || "");
  var row = findIndexRow_(key);
  if (!row) return { ok: true, removed: false };
  if (row.driveId) { try { DriveApp.getFileById(row.driveId).setTrashed(true); } catch (e) {} }
  removeIndexRow_(key);
  writeLinkToDataSheet_(body.vehicle_id, body.doc_type, ""); // clear the link
  return { ok: true, removed: true };
}

// ----------------------------- DRIVE -------------------------------------- //
function getRootFolder_() {
  var it = DriveApp.getFoldersByName(ROOT_FOLDER_NAME);
  return it.hasNext() ? it.next() : DriveApp.createFolder(ROOT_FOLDER_NAME);
}
function getVehicleFolder_(vehicleId) {
  var root = getRootFolder_();
  var it = root.getFoldersByName(vehicleId);
  return it.hasNext() ? it.next() : root.createFolder(vehicleId);
}
function guessExt_(filename, mime) {
  var f = String(filename || "");
  var dot = f.lastIndexOf(".");
  if (dot > -1) return f.substring(dot);
  if (/pdf/i.test(mime)) return ".pdf";
  if (/png/i.test(mime)) return ".png";
  if (/jpe?g/i.test(mime)) return ".jpg";
  return "";
}

// ----------------------------- INDEX SHEET -------------------------------- //
function indexSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(INDEX_SHEET);
  if (!sh) {
    sh = ss.insertSheet(INDEX_SHEET);
    sh.appendRow(["key", "vehicle_id", "doc_type", "file_url", "file_name", "drive_id", "uploaded_at"]);
  }
  return sh;
}
function readIndex_() {
  var sh = indexSheet_();
  var values = sh.getDataRange().getValues();
  var map = {};
  for (var r = 1; r < values.length; r++) {
    var row = values[r];
    if (!row[0]) continue;
    map[row[0]] = { url: row[3], name: row[4], uploadedAt: row[6] };
  }
  return map;
}
function findIndexRow_(key) {
  var sh = indexSheet_();
  var values = sh.getDataRange().getValues();
  for (var r = 1; r < values.length; r++) {
    if (values[r][0] === key) return { row: r + 1, driveId: values[r][5] };
  }
  return null;
}
function upsertIndex_(key, vehicleId, docType, url, name, driveId) {
  var sh = indexSheet_();
  var when = new Date().toISOString();
  var found = findIndexRow_(key);
  var rowVals = [key, vehicleId, docType, url, name, driveId, when];
  if (found) sh.getRange(found.row, 1, 1, rowVals.length).setValues([rowVals]);
  else sh.appendRow(rowVals);
}
function removeIndexRow_(key) {
  var sh = indexSheet_();
  var found = findIndexRow_(key);
  if (found) sh.deleteRow(found.row);
}

// ----------------------------- DATA SHEET WRITE-BACK ---------------------- //
function dataSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (DATA_SHEET) return ss.getSheetByName(DATA_SHEET);
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getName() === INDEX_SHEET) continue;
    var headers = sheets[i].getRange(1, 1, 1, sheets[i].getLastColumn()).getValues()[0]
                   .map(function (h) { return String(h).trim().toLowerCase().replace(/ /g, "_"); });
    if (headers.indexOf("vehicle_id") > -1) return sheets[i];
  }
  return null;
}
function writeLinkToDataSheet_(vehicleId, docType, url) {
  try {
    var col = FILE_COLUMNS[docType];
    if (!col) return;
    var sh = dataSheet_();
    if (!sh) return;
    var headers = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0]
                   .map(function (h) { return String(h).trim().toLowerCase().replace(/ /g, "_"); });
    var idCol = headers.indexOf("vehicle_id");
    var fileCol = headers.indexOf(col);
    if (idCol < 0) return;
    if (fileCol < 0) { // add the column if the sheet doesn't have it yet
      fileCol = headers.length;
      sh.getRange(1, fileCol + 1).setValue(col);
    }
    var ids = sh.getRange(2, idCol + 1, Math.max(sh.getLastRow() - 1, 1), 1).getValues();
    for (var r = 0; r < ids.length; r++) {
      if (String(ids[r][0]).trim() === String(vehicleId).trim()) {
        sh.getRange(r + 2, fileCol + 1).setValue(url);
        return;
      }
    }
  } catch (e) { /* write-back is best-effort; the DocFiles index is the source of truth */ }
}

// ----------------------------- UTIL --------------------------------------- //
function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
