/**
 * Person A - Google Apps Script Web App (REFERENCE IMPLEMENTATION)
 * ================================================================
 * This file is the version-controlled reference for the Apps Script project
 * that backs Person A's Streamlit frontend (ui_common.py). If the deployed
 * script in the Apps Script editor ever differs, the deployed one is the
 * source of truth for the live spreadsheet - use this file to review,
 * restore or re-deploy it.
 *
 * Spreadsheet: https://docs.google.com/spreadsheets/d/1hNjUhKQn-QfZp3VWd_gzLQsCQoAzYHtahTSkFk1mE8U/edit
 * Records sheet columns: type | id | data | updatedAt
 *
 * Protocol (must stay in sync with ui_common.py):
 *   GET  {url}?key={API_SECRET}&type=expenses|budgets
 *        -> {"ok": true, "records": [{type, id, data, updatedAt}, ...]}
 *   POST {url}  body JSON {"key": ..., "type": ..., "id": "...", "data": {...}}
 *        -> {"ok": true, "id": "..."}   (upsert: replaces the row with this id)
 *   Any failure -> {"ok": false, "error": "..."}
 *
 * SECURITY
 *   - The secret is read from Script Properties (key: API_SECRET).
 *     Project Settings -> Script Properties -> add API_SECRET.
 *   - Never hardcode the secret here, and never paste it into chat/docs.
 *   - The secret was exposed in a chat in 2026-11: ROTATE it (update the
 *     Script Property, update Streamlit Secrets, no redeploy needed).
 *
 * Deployment: Deploy -> New deployment -> Web app
 *   Execute as: Me | Who has access: Anyone
 *   Copy the /exec URL into Streamlit Secrets as API_URL.
 */

var SHEET_NAME = 'Records';
var TYPES = { expenses: true, budgets: true };

function getSecret_() {
  return PropertiesService.getScriptProperties().getProperty('API_SECRET') || '';
}

function sheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
    sh.appendRow(['type', 'id', 'data', 'updatedAt']);
  }
  return sh;
}

function respond_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function doGet(e) {
  var key = (e && e.parameter && e.parameter.key) || '';
  if (!key || key !== getSecret_()) return respond_({ ok: false, error: 'Unauthorized' });
  var type = (e && e.parameter && e.parameter.type) || '';
  if (!TYPES[type]) return respond_({ ok: false, error: 'Unknown type' });

  var sh = sheet_();
  var values = sh.getDataRange().getValues();
  var records = [];
  for (var i = 1; i < values.length; i++) {
    if (String(values[i][0]) === type) {
      records.push({
        type: values[i][0],
        id: values[i][1],
        data: values[i][2],
        updatedAt: values[i][3]
      });
    }
  }
  return respond_({ ok: true, records: records });
}

function doPost(e) {
  var body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) { /* fall through */ }
  var key = body.key || '';
  if (!key || key !== getSecret_()) return respond_({ ok: false, error: 'Unauthorized' });
  var type = body.type || '';
  if (!TYPES[type]) return respond_({ ok: false, error: 'Unknown type' });
  if (body.id === undefined || body.id === null || body.id === '') {
    return respond_({ ok: false, error: 'Missing id' });
  }

  var sh = sheet_();
  var values = sh.getDataRange().getValues();
  var targetRow = -1;
  for (var i = 1; i < values.length; i++) {
    if (String(values[i][0]) === type && String(values[i][1]) === String(body.id)) {
      targetRow = i + 1; // 1-based sheet row
      break;
    }
  }
  var stamp = new Date().toISOString();
  if (targetRow === -1) {
    sh.appendRow([type, String(body.id), JSON.stringify(body.data || {}), stamp]);
  } else {
    sh.getRange(targetRow, 3).setValue(JSON.stringify(body.data || {}));
    sh.getRange(targetRow, 4).setValue(stamp);
  }
  return respond_({ ok: true, id: String(body.id) });
}
