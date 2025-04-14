# --- START OF FILE app/google_drive_sync.py ---
import os
import io
import pickle
import logging
import time
import shutil
import json
from typing import Optional, Any, List, Dict, Iterator, Tuple, NamedTuple
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone # Added for timestamp parsing
import requests.exceptions # For specific error handling

# Attempt Google library imports
try:
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build, Resource
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload, BatchHttpRequest
    from googleapiclient.errors import HttpError
    GOOGLE_LIBS_AVAILABLE = True
except ImportError:
    GOOGLE_LIBS_AVAILABLE = False
    Resource = Any; HttpError = ConnectionError; Request = Any; InstalledAppFlow = Any
    MediaFileUpload = Any; MediaIoBaseDownload = Any; BatchHttpRequest = Any
    class RequestsExceptions: ConnectionError = ConnectionError
    requests = type('requests', (object,), {'exceptions': RequestsExceptions})()

# --- Logger ---
logger = logging.getLogger(__name__)

# --- Constants & Types ---
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SYNC_SUCCESS = 0; SYNC_FAILED_OFFLINE = 1; SYNC_FAILED_AUTH = 2
SYNC_FAILED_API = 3; SYNC_FAILED_LOCAL_IO = 4; SYNC_FAILED_PARTIAL = 5
SYNC_FAILED_OTHER = 6; SYNC_FAILED_INIT = 7
MAX_CONCURRENT_WORKERS = 4

class FileMetadata(NamedTuple):
    name: str
    local_path: str
    id: Optional[str] = None
    modified_time: Optional[float] = None # Unix timestamp

# --- GoogleDriveSyncManager Class ---
class GoogleDriveSyncManager:
    """Manages GDrive auth, folder ops, and delta synchronization."""

    def __init__(
        self,
        credentials_path: str, token_path: str, app_folder_name: str,
        persistent_store_base_path: str
    ):
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.app_folder_name = app_folder_name
        self.persistent_store_base_path = persistent_store_base_path
        self._service: Optional[Resource] = None
        self._service_validated = False
        self.is_available = GOOGLE_LIBS_AVAILABLE
        self.app_folder_id_cache: Optional[str] = None
        if not self.is_available: logger.critical("GDrive Sync Disabled: Google libs not found.")

    def _authenticate(self) -> Optional[Resource]:
        """Handles OAuth2 authentication and returns the Drive service."""
        if not self.is_available: return None
        if self._service and self._service_validated: return self._service
        if self._service:
            try: self._service.about().get(fields='user').execute(); self._service_validated = True; return self._service
            except Exception as e: logger.warning(f"GDrive cache check failed ({e}). Re-auth."); self._service = None; self._service_validated = False

        creds = None; logger.info("Attempting GDrive authentication...")
        try:
            if os.path.exists(self.token_path):
                with open(self.token_path, 'rb') as token:
                    try: creds = pickle.load(token)
                    except Exception: logger.warning("Token file corrupt. Re-auth.")
            if not creds or not creds.valid:
                refreshed = False
                if creds and creds.expired and creds.refresh_token:
                    try: creds.refresh(Request()); refreshed = True; logger.info("GDrive credentials refreshed.")
                    except Exception as e: logger.error(f"Failed GDrive token refresh: {e}.")
                if not refreshed:
                    if not os.path.exists(self.credentials_path): logger.critical(f"Creds file '{self.credentials_path}' not found."); return None
                    flow = InstalledAppFlow.from_client_secrets_file(self.credentials_path, SCOPES)
                    # IMPORTANT: run_local_server needs browser access. Use run_console() or web flow for servers.
                    creds = flow.run_local_server(port=0)
                    logger.info("GDrive OAuth flow completed.")
                    with open(self.token_path, 'wb') as token: pickle.dump(creds, token)
                    logger.info(f"GDrive credentials saved to {self.token_path}")
            service = build('drive', 'v3', credentials=creds)
            logger.info("GDrive API service built successfully.")
            self._service = service; self._service_validated = True
            return service
        except FileNotFoundError: logger.critical(f"Creds file '{self.credentials_path}' missing."); return None
        except Exception as e:
            logger.error(f"GDrive auth error: {e}", exc_info=True)
            if os.path.exists(self.token_path): try: os.remove(self.token_path) except OSError: pass
            return None

    def _get_service(self) -> Optional[Resource]:
        """Ensures service is authenticated and returns it."""
        if not self._service or not self._service_validated: self._authenticate()
        return self._service

    def _get_local_user_path(self, user_id: int) -> str:
        return os.path.join(self.persistent_store_base_path, f"user_{user_id}")

    def _find_item(self, query: str) -> Optional[str]:
        """Finds a single file/folder ID."""
        service = self._get_service()
        if not service: return None
        try:
            res = service.files().list(q=query, spaces='drive', fields='files(id)', pageSize=1).execute()
            return res.get('files', [])[0]['id'] if res.get('files') else None
        except Exception as e: logger.error(f"GDrive API error finding item '{query}': {e}"); return None

    def _create_folder(self, name: str, parent_id: Optional[str] = None) -> Optional[str]:
        """Creates a folder, returns ID."""
        service = self._get_service()
        if not service: return None
        logger.info(f"Creating GDrive folder '{name}'...")
        meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id: meta['parents'] = [parent_id]
        try:
            folder = service.files().create(body=meta, fields='id').execute(); fid = folder.get('id')
            logger.info(f"Created folder '{name}' ID: {fid}")
            return fid
        except Exception as e: logger.error(f"GDrive API error creating folder '{name}': {e}"); return None

    def find_or_create_app_folder(self) -> Optional[str]:
        """Finds or creates the main app folder."""
        if self.app_folder_id_cache: return self.app_folder_id_cache
        service = self._get_service()
        if not service: return None
        query = f"mimeType='application/vnd.google-apps.folder' and name='{self.app_folder_name}' and 'root' in parents and trashed=false"
        folder_id = self._find_item(query)
        if not folder_id: folder_id = self._create_folder(self.app_folder_name)
        if folder_id: logger.info(f"Using app folder '{self.app_folder_name}' (ID: {folder_id}).")
        self.app_folder_id_cache = folder_id
        return folder_id

    def find_or_create_user_folder_id(self, user_id: int) -> Optional[str]:
        """Finds/creates the user-specific folder."""
        app_folder_id = self.find_or_create_app_folder()
        if not app_folder_id: return None
        user_folder_name = f"user_{user_id}"; folder_id = None
        query = f"mimeType='application/vnd.google-apps.folder' and name='{user_folder_name}' and '{app_folder_id}' in parents and trashed=false"
        try: folder_id = self._find_item(query)
        except Exception: pass # Ignore find error, proceed to create
        if not folder_id: folder_id = self._create_folder(user_folder_name, parent_id=app_folder_id)
        if folder_id: logger.debug(f"Using user folder '{user_folder_name}' (ID: {folder_id}).")
        return folder_id

    def _list_local_files(self, user_id: int) -> Dict[str, FileMetadata]:
        """Lists local files with metadata."""
        local_path = self._get_local_user_path(user_id); local_files = {}
        if not os.path.isdir(local_path): return local_files
        try:
            for name in os.listdir(local_path):
                full_path = os.path.join(local_path, name)
                if os.path.isfile(full_path) and name != '.last_modified':
                    try: mtime = os.path.getmtime(full_path); local_files[name] = FileMetadata(name=name, local_path=full_path, modified_time=mtime)
                    except OSError: pass
            return local_files
        except OSError as e: logger.error(f"User {user_id}: Failed list local files: {e}"); raise

    def _parse_gdrive_mtime(self, mtime_str: Optional[str]) -> Optional[float]:
         """Parses GDrive RFC3339 timestamp string to Unix float."""
         if not mtime_str: return None
         try: return datetime.strptime(mtime_str, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc).timestamp()
         except ValueError: # Try without milliseconds
              try: return datetime.strptime(mtime_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
              except ValueError: logger.warning(f"Could not parse modifiedTime: {mtime_str}"); return None

    def _list_remote_files(self, user_folder_id: str) -> Dict[str, FileMetadata]:
        """Lists remote files with metadata."""
        service = self._get_service(); remote_files = {}
        if not service or not user_folder_id: return remote_files
        page_token = None
        try:
            while True:
                res = service.files().list(
                    q=f"'{user_folder_id}' in parents and trashed=false", spaces='drive',
                    fields='nextPageToken, files(id, name, modifiedTime)', pageSize=200, pageToken=page_token
                ).execute()
                for item in res.get('files', []):
                    mtime_ts = self._parse_gdrive_mtime(item.get('modifiedTime'))
                    name, fid = item.get('name'), item.get('id')
                    if name and fid: remote_files[name] = FileMetadata(name=name, id=fid, modified_time=mtime_ts, local_path='')
                page_token = res.get('nextPageToken')
                if page_token is None: break
            return remote_files
        except Exception as e: logger.error(f"Failed listing remote files in {user_folder_id}: {e}"); raise

    def _is_local_newer(self, local_meta: FileMetadata, remote_meta: FileMetadata) -> bool:
        """Check if local file is newer than remote (with 2s buffer)."""
        if not local_meta.modified_time or not remote_meta.modified_time: return True
        return local_meta.modified_time > (remote_meta.modified_time + 2)

    def _upload_file_worker(self, local_meta: FileMetadata, remote_meta: Optional[FileMetadata], user_folder_id: str) -> Tuple[str, bool, Optional[Exception]]:
        """Worker function to upload/update a single file."""
        service = self._get_service()
        if not service: return local_meta.name, False, RuntimeError("GDrive service unavailable")
        try:
            file_metadata = {'name': local_meta.name}
            media = MediaFileUpload(local_meta.local_path, mimetype='application/octet-stream', resumable=True)
            request = None; action = "Uploading new"
            if remote_meta and remote_meta.id: # Update
                action = "Updating"; request = service.files().update(fileId=remote_meta.id, media_body=media, fields='id')
            else: # Create
                file_metadata['parents'] = [user_folder_id]; request = service.files().create(body=file_metadata, media_body=media, fields='id')
            logger.debug(f"{action} GDrive file: {local_meta.name}")
            response = None; done = False
            while response is None or not done: _, response = request.next_chunk() # Progress reporting removed for brevity
            return local_meta.name, True, None
        except Exception as e: return local_meta.name, False, e

    def _batch_delete_callback(self, request_id, response, exception):
        """Callback for batch delete requests."""
        if exception: logger.error(f"Batch delete error for request {request_id}: {exception}")

    def _execute_batch_delete(self, files_to_prune: List[Tuple[str, str]]) -> bool:
        """Executes file deletions using BatchHttpRequest."""
        service = self._get_service()
        if not service or not files_to_prune: return True
        batch = BatchHttpRequest(callback=self._batch_delete_callback)
        for name, file_id in files_to_prune: batch.add(service.files().delete(fileId=file_id))
        try: logger.info(f"Executing batch delete for {len(files_to_prune)} files..."); batch.execute(); return True
        except Exception as e: logger.error(f"Error executing batch delete: {e}"); return False

    # --- Main Sync Methods ---
    def sync_db_from_gdrive(self, user_id: int) -> int:
        """Downloads files from user's GDrive folder to local (OVERWRITE)."""
        service = self._get_service()
        if not service: return SYNC_FAILED_INIT
        user_folder_id = self.find_or_create_user_folder_id(user_id)
        if not user_folder_id: return SYNC_FAILED_API # Could be permission/creation error

        local_path = self._get_local_user_path(user_id)
        logger.info(f"User {user_id}: Syncing FROM GDrive {user_folder_id} to {local_path}...")
        start_time, files_downloaded = time.time(), 0
        try:
            if os.path.exists(local_path): shutil.rmtree(local_path)
            os.makedirs(local_path, exist_ok=True)
            page_token = None
            while True:
                res = service.files().list(q=f"'{user_folder_id}' in parents and trashed=false", spaces='drive', fields='nextPageToken, files(id, name)', pageToken=page_token, pageSize=100).execute()
                files = res.get('files', [])
                if not files and page_token is None: break
                for item in files:
                    file_id, file_name = item.get('id'), item.get('name')
                    if not file_id or not file_name: continue
                    local_file = os.path.join(local_path, file_name)
                    logger.debug(f"Downloading: {file_name} (ID: {file_id})")
                    request = service.files().get_media(fileId=file_id); fh = io.BytesIO()
                    downloader = MediaIoBaseDownload(fh, request); done = False
                    while not done: _, done = downloader.next_chunk()
                    with open(local_file, 'wb') as f: fh.seek(0); f.write(fh.read())
                    files_downloaded += 1
                page_token = res.get('nextPageToken');
                if page_token is None: break
            logger.info(f"User {user_id}: GDrive sync download ({files_downloaded} files) complete in {time.time() - start_time:.2f}s.")
            return SYNC_SUCCESS
        except HttpError as e: logger.error(f"API error sync from GDrive user {user_id}: {e}"); status=getattr(e,'resp',{}).status; return SYNC_FAILED_AUTH if status in [401,403] else (SYNC_FAILED_API if status and status<500 else SYNC_FAILED_OFFLINE)
        except (requests.exceptions.ConnectionError, ConnectionError) as e: logger.warning(f"Network error sync from GDrive user {user_id}: {e}"); return SYNC_FAILED_OFFLINE
        except OSError as e: logger.error(f"Local IO error sync from GDrive user {user_id}: {e}"); return SYNC_FAILED_LOCAL_IO
        except Exception as e: logger.exception(f"Unexpected error sync from GDrive user {user_id}: {e}"); return SYNC_FAILED_OTHER

    def sync_db_to_gdrive(self, user_id: int) -> int:
        """Uploads local changes to GDrive using delta sync. Returns SYNC_* status."""
        service = self._get_service()
        if not service: return SYNC_FAILED_INIT
        user_folder_id = self.find_or_create_user_folder_id(user_id)
        if not user_folder_id: return SYNC_FAILED_API

        logger.info(f"User {user_id}: Starting DELTA sync TO GDrive folder {user_folder_id}...")
        start_time = time.time(); sync_status = SYNC_FAILED_PARTIAL; prune_successful = True
        try:
            remote_files = self._list_remote_files(user_folder_id)
            local_files = self._list_local_files(user_id)
            files_to_upload, files_to_prune = [], []; remote_names, local_names = set(remote_files), set(local_files)
            for name, l_meta in local_files.items():
                r_meta = remote_files.get(name)
                if not r_meta or self._is_local_newer(l_meta, r_meta): files_to_upload.append((l_meta, r_meta))
            for name, r_meta in remote_files.items():
                if name not in local_names and r_meta.id: files_to_prune.append((name, r_meta.id))

            if not files_to_upload and not files_to_prune: logger.info(f"User {user_id}: No changes detected."); return SYNC_SUCCESS
            logger.info(f"User {user_id}: Delta: {len(files_to_upload)} up, {len(files_to_prune)} prune.")

            # Execute uploads concurrently
            upload_errors = 0
            if files_to_upload:
                logger.info(f"User {user_id}: Starting concurrent upload...")
                with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_WORKERS) as executor:
                    futures = {executor.submit(self._upload_file_worker, m[0], m[1], user_folder_id): m[0].name for m in files_to_upload}
                    for future in as_completed(futures):
                        fname = futures[future]
                        try: _, success, error = future.result()
                        except Exception as exc: success, error = False, exc
                        if not success:
                            upload_errors += 1; logger.error(f"User {user_id}: Failed upload {fname}. Error: {error}")
                            # Determine failure code and return immediately on critical upload error
                            if isinstance(error, HttpError): status=getattr(error,'resp',{}).status; return SYNC_FAILED_AUTH if status in [401,403] else (SYNC_FAILED_API if status and status<500 else SYNC_FAILED_OFFLINE)
                            if isinstance(error, requests.exceptions.RequestException): return SYNC_FAILED_OFFLINE
                            return SYNC_FAILED_OTHER # General upload fail

            # Execute pruning (only if uploads were okay)
            if upload_errors == 0 and files_to_prune:
                logger.info(f"User {user_id}: Starting pruning...")
                prune_successful = self._execute_batch_delete(files_to_prune)
                if not prune_successful: logger.warning(f"User {user_id}: Pruning had errors.")

            # Determine final status
            if upload_errors == 0 and prune_successful: sync_status = SYNC_SUCCESS
            elif upload_errors == 0 and not prune_successful: sync_status = SYNC_FAILED_PARTIAL
            # Else: upload errors already returned specific code

            logger.info(f"User {user_id}: GDrive sync TO finished in {time.time() - start_time:.2f}s. Status: {sync_status}")
            return sync_status

        except (requests.exceptions.ConnectionError, ConnectionError) as e: logger.warning(f"Network error sync TO GDrive user {user_id}: {e}"); return SYNC_FAILED_OFFLINE
        except OSError as e: logger.error(f"Local file error sync TO GDrive user {user_id}: {e}"); return SYNC_FAILED_LOCAL_IO
        except Exception as e:
            logger.exception(f"Unexpected failure sync TO GDrive user {user_id}: {e}")
            if isinstance(e, HttpError): status=getattr(e,'resp',{}).status; return SYNC_FAILED_AUTH if status in [401,403] else (SYNC_FAILED_API if status and status<500 else SYNC_FAILED_OFFLINE)
            return SYNC_FAILED_OTHER
# --- END OF FILE app/google_drive_sync.py ---