"""This module uploads files to Google Drive.

If the file already exists (in that folder, if selected) it will
overwrite it only if the modified date in the drive is older than the
modified date of file to be uploaded, unless --force is set.

This module uses a custom 'modified date' property in drive file's
metadata, so manually uploaded files must be forced.
"""

import argparse
import httplib2
import os

from apiclient import discovery
from apiclient.http import MediaFileUpload
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage


arg_help = [
    "Save or overwrite files to Google Drive. The last modified date of the "
        "file is written to a custom property, and will only overwrite without"
        " --force if this date is before the file's last modified date.",
    "List of files seperated by comma (and no spaces) (required).",
    "Home directory to look for items in file_list. If omitted include the "
        "full path in the file list or relative path to script will be used.",
    "Folder name to upload files to in Google Drive. If omitted, files will be"
        " placed in root directory.",
    "Force overwrite.",
    "Prints last modified dates and whether 'force' is required to upload.",
    "Set the mimetype for all files to be uploaded. Generally, Google Drive "
        "handles this automatically."
]

parent = tools.argparser
group = parent.add_argument_group('standard')
exclusive_group = parent.add_mutually_exclusive_group()
parent.add_argument("-f", "--file_list", help=arg_help[1], required=True)
parent.add_argument("-d", "--home_dir", help=arg_help[2])
parent.add_argument("--folder", help=arg_help[3])
exclusive_group.add_argument("--force", help=arg_help[4], action='store_true')
exclusive_group.add_argument("-c", "--check", help=arg_help[5], action='store_true')
parent.add_argument("--mimetype", help=arg_help[6])
flags = argparse.ArgumentParser(
    parents=[parent],
    description=arg_help[0]
).parse_args()

SCOPES = 'https://www.googleapis.com/auth/drive'
CLIENT_SECRET_FILE = 'client_secret.json'
APPLICATION_NAME = 'Google Drive API'
FOLDER_MIMETYPE = 'application/vnd.google-apps.folder'

SCRIPT_DIR = os.path.split(os.path.realpath(__file__))[0]


# Taken from https://developers.google.com/drive/v3/web/quickstart/python
def get_credentials(script_dir):
    """Gets valid user credentials from storage.

    If nothing has been stored, or if the stored credentials are invalid,
    the OAuth2 flow is completed to obtain the new credentials.

    :type script_dir: str

    Returns:
        Credentials, the obtained credential.
    """
    credential_dir = os.path.join(script_dir, 'credentials')
    if not os.path.exists(credential_dir):
        os.makedirs(credential_dir)
    credential_path = os.path.join(credential_dir,
                                   'cmdrive_credentials.json')

    store = Storage(credential_path)
    credentials = store.get()
    if not credentials or credentials.invalid:
        secret_file = os.path.join(script_dir, CLIENT_SECRET_FILE)
        flow = client.flow_from_clientsecrets(secret_file, SCOPES)
        flow.user_agent = APPLICATION_NAME
        if flags:
            credentials = tools.run_flow(flow, store, flags)
        else:  # Needed only for compatibility with Python 2.6
            credentials = tools.run(flow, store)
        print('Storing credentials to ' + credential_path)
    return credentials


class Uploader(object):
    """Docstring."""

    def __init__(self):
        self.file_list = flags['file_list'].split(',')
        if flags['folder']:
            self.drive_folder = flags['folder']
        else:
            self.drive_folder = "root"
        if flags['mimetype']:
            self.mimetype = flags['mimetype']
        else:
            self.mimetype = None
        credentials = get_credentials(SCRIPT_DIR)
        http = credentials.authorize(httplib2.Http())
        self.service = discovery.build('drive', 'v3', http=http)

    def find_folder(self):
        """Return the requested folder in Google Drive.
        If the folder file is not located, create it.
        """
        if self.drive_folder == "root":
            return self.drive_folder
        folder = self.service.files().list(
            q="mimeType='{}' and name='{}'".format(FOLDER_MIMETYPE,
                                                   self.drive_folder),
            spaces='drive').execute()['files']
        if not folder:
            return self.make_folder(self.drive_folder)['id']
        else:
            return folder[0]['id']

    def make_folder(self, folder_name):
        """Create Google Drive folder.

        :type folder_name: str
        """
        file_metadata = {
            'name': folder_name,
            'mimeType': FOLDER_MIMETYPE
        }
        folder = self.service.files().create(
            body=file_metadata,
            fields='files(id, name)').execute()
        print '{} folder created, ID: {}'.format(folder_name, folder.get('id'))
        return {'file': folder, 'id': folder.get('id')}

    def find_drive_files(self, filename, folder_id):
        """Return a list of files named filename if 'folder_id' is a
        parent folder. Return empty list if none are found. Currently
        only the first file is used.

        :type filename: str
        :type folder_id: str
        """
        files = self.service.files().list(
            q="'{}' in parents and name='{}' and trashed=false".format(
                folder_id, filename),
            fields="files(id, name, properties)").execute()['files']
        return files[0] if files else None

    def upload(self, force):
        """Upload files to GDrive. Only overwrite existing files if
        they were more recently modified, or if force == True.

        :type force: bool
        """
        for local_file in self.file_list:
            filename = os.path.split(local_file)[-1]
            if flags['home_dir']:
                filepath = os.path.join(flags['home_dir'], local_file)
            else:
                filepath = os.path.join(SCRIPT_DIR, local_file)
            file_last_update = int(os.path.getmtime(filepath))
            file_metadata = {
                'name': filename,
                'properties': {'modified': file_last_update}
            }
            folder_id = self.find_folder()
            file_found = self.find_drive_files(filename, folder_id)
            if file_found:
                if not force:
                    try:
                        modified = int(file_found[0]['properties']['modified'])
                    except KeyError:
                        print "Properties not defined. Use force upload."
                        continue
                    if modified > file_last_update:
                        print ("File {} was last modified after local file. "
                               "FILE WAS NOT UPDATED!!! Force upload "
                               "required.").format(filename)
                        continue
                    elif modified == file_last_update:
                        print ("File {} has same last modified date. FILE WAS "
                               "NOT UPDATED!!! Force upload "
                               "required.").format(filename)
                        continue

                media = MediaFileUpload(filepath,
                                        mimetype=self.mimetype)
                self.service.files().update(
                    fileId=file_found[0]['id'],
                    media_body=media,
                    body=file_metadata
                ).execute()
                print "File {} updated.".format(filepath)
                continue

            file_metadata['parents'] = [ folder_id ]
            media = MediaFileUpload(filepath,
                                    mimetype=self.mimetype)
            self.service.files().create(
                body=file_metadata,
                media_body=media).execute()
            print "File {} uploaded.".format(filepath)

    def run_check(self):
        pass


def main():
    GDrive = Uploader()
    if flags['check']:
        GDrive.run_check()
        return
    force = True if flags['force'] else False
    GDrive.upload(force)


if __name__ == '__main__':
    main()
    raw_input("Press enter to close.")










