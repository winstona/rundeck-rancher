from requests.auth import HTTPBasicAuth
from websocket import create_connection
from dateutil.parser import parse
import websocket
import StringIO
import requests
import logging
import hashlib
import base64
import json
import time
import sys
import os
import re

from _shared import *

def parse_logs(message, newer_than_timestamp=None):
    # sometimes we get single lines, sometimes we get all the logs at once...
    string_buf = StringIO.StringIO(message)
    for log_line in string_buf:
        if len(log_line.strip()) == 0:
            continue
        log_line = log_line.strip()
        msg_match = re.match(log_re_pattern, log_line, re.MULTILINE | re.DOTALL)
        if not msg_match:
            log("[ E ] [PARSE_ERROR]>>> " + log_line + " <<<[/PARSE_ERROR]")
            raise Exception("Failed to read log format, regex does not match!")
        # keep track of log line hashes so we can ignore already read lines if we need to reconnect and fetch logs
        m = hashlib.md5()
        m.update(log_line)
        message_text_md5 = m.hexdigest()
        if message_text_md5 in seen_logs_md5:
            continue
        seen_logs_md5.append(message_text_md5)
        # parse log format
        is_error = (int(msg_match.group(1)) == 2)
        log_date = parse(msg_match.group(2)).replace(tzinfo=None)
        log_message = msg_match.group(3)
        if newer_than_timestamp is None or log_date > newer_than_timestamp:
            log(log_message)
            if is_error:
                raise Exception(log_message)


@retry()
def get_container_information():
    api_url = "{}/container/{}".format(api_base_url, node_id)
    api_res = requests.get(api_url, auth=api_auth)
    api_res_json = api_res.json()
    # log(json.dumps(api_res_json, indent=2))
    if not api_res.status_code < 300:
        raise Exception("Failed to read container information: API error, code \"{} ({})\"!".format(api_res_json['code'], api_res_json['status']))
    return api_res_json


class ErrorLogger(logging.StreamHandler):
    has_error = False
    last_error = None

    def clear(self):
        self.has_error = False
        self.last_error = None

    def emit(self, record):
        msg = self.format(record)
        self.has_error = True
        self.last_error = msg
        log("[ E ] {}".format(msg))
        raise Exception(msg)
    pass


def check_os_env(var, txt):
    if var is None or len(var) == 0:
        raise ValueError(txt)

log_handler = ErrorLogger()
logger = logging.getLogger('websocket')
logger.setLevel(logging.ERROR)
logger.addHandler(log_handler)
log_re_pattern = r"^(\d*)\s+?(.*?Z)\s?(.*)?$"

# todo: remove this when rundeck bug is resolved
#cattle_config = json.load(open("/rancher-auth-workaround.json"))

#api_base_url = cattle_config['host'] # os.environ['CATTLE_CONFIG_URL']
#api_access_key = cattle_config['access_key'] #  os.environ['CATTLE_ACCESS_KEY']
#api_secret_key = cattle_config['secret_key'] #  os.environ['CATTLE_SECRET_KEY']

#print os.environ

try:
    api_base_url = os.environ.get('RD_CONFIG_CATTLE_CONFIG_URL')
    check_os_env(api_base_url, "Cattle URL is not set")
except ValueError:
    api_base_url = os.environ.get('RD_NODE_RANCHER_URL')
    check_os_env(api_base_url, "Cattle or Rancher URL is not set")

api_access_key = os.environ.get('RD_CONFIG_CATTLE_ACCESS_KEY')
check_os_env(api_access_key,"Cattle acces key is not set")

api_secret_key = os.environ.get('RD_CONFIG_CATTLE_SECRET_KEY')
check_os_env(api_secret_key,"Cattle secret key is not set")

api_auth = HTTPBasicAuth(api_access_key, api_secret_key)

ws_auth_header = {'Authorization': "Basic {}".format(base64.b64encode("{}:{}".format(api_access_key, api_secret_key)))}

environment_id = os.environ.get('RD_NODE_ENVIRONMENT_ID', '')
check_os_env(environment_id,"Can't run, environment ID is not set!")

node_id = os.environ.get('RD_NODE_ID', '')
check_os_env(node_id,"Can't run, node ID is not set!")

node_tty = (os.environ.get('RD_NODE_TTY', 'true').lower() == 'true')
