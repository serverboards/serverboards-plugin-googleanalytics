#!/usr/bin/python3

import serverboards, requests
import os, json, sys, time, datetime
import httplib2, threading

from serverboards import rpc
from oauth2client import client
from urllib.parse import urlencode, urljoin
from googleapiclient import discovery

#DISCOVERY_URI = ('https://analyticsreporting.googleapis.com/$discovery/rest')
OAUTH_AUTH_URL="https://accounts.google.com/o/oauth2/auth"
OAUTH_AUTH_TOKEN_URL="https://accounts.google.com/o/oauth2/token"
OAUTH_AUTH_REVOKE_URL="https://accounts.google.com/o/oauth2/token"

SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']
settings = {}

class ServerboardsStorage(client.Storage):
    def __init__(self, id=None):
        serverboards.debug("%s"%(id))
        assert id
        self.id=id
        super(ServerboardsStorage, self).__init__(lock=threading.Lock())
    def locked_get(self):
        content = rpc.call("plugin.data.get", "credentials-"+self.id)
        if not content:
            return None
        try:
            credentials = client.OAuth2Credentials.from_json(content)
            credentials.set_store(self)
            return credentials
        except:
            pass
        return None

    def locked_put(self, credentials):
        rpc.call("plugin.data.update", "credentials-"+self.id, credentials.to_json())
    def locked_delete(self):
        rpc.call("plugin.data.delete", "credentials-"+self.id)

def ensure_settings():
    if "client_id" not in settings:
        data = serverboards.rpc.call("settings.get", "serverboards.google.analytics/settings")
        if not data:
            raise Exception("Google Analytics Integration not configured. Check system settings.")
        settings.update(data)

        base = serverboards.rpc.call("settings.get", "serverboards.core.settings/base")
        settings.update(base)

@serverboards.rpc_method
def authorize_url(service, **kwargs):
    service_id=service["uuid"]
    ensure_settings()

    params={
        "response_type" : "code",
        "client_id" : settings["client_id"],
        "redirect_uri" : urljoin(settings["base_url"], "/static/serverboards.google.analytics/auth.html"),
        "scope": 'https://www.googleapis.com/auth/analytics.readonly',
        "state": service_id
    }
    url = OAUTH_AUTH_URL+"?"+urlencode(params)
    return url

@serverboards.rpc_method
def store_code(service_id, code):
    ensure_settings()

    """
    Stores the code and get a refresh token and a access token
    """
    params={
        "code": code,
        "client_id": settings["client_id"],
        "client_secret": settings["client_secret"],
        "redirect_uri": urljoin(settings["base_url"], "/static/serverboards.google.analytics/auth.html"),
        "grant_type": "authorization_code",
    }
    response = requests.post(OAUTH_AUTH_TOKEN_URL, params)
    js = response.json()
    if 'error' in js:
        raise Exception(js['error_description'])
    storage = ServerboardsStorage(service_id)
    credentials = client.OAuth2Credentials(
        access_token=js["access_token"],
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
        refresh_token=js.get("refresh_token"),
        token_expiry=datetime.datetime.utcnow() + datetime.timedelta(seconds=int(js["expires_in"])),
        token_uri=OAUTH_AUTH_TOKEN_URL,
        user_agent=None,
        revoke_uri=OAUTH_AUTH_REVOKE_URL,
        token_response=js,
        scopes=SCOPES,
        token_info_uri="https://www.googleapis.com/oauth2/v3/tokeninfo"
    )
    credentials.set_store(storage)
    storage.put(credentials)

    return "ok"

analytics = {}
def get_analytics(service_id, version='v4'):
    serverboards.debug("%s"%(service_id))

    ank=(service_id, version)
    if not analytics.get(ank):
        storage = ServerboardsStorage(service_id)
        credentials = storage.get()
        if not credentials:
            raise Exception("Invalid credentials. Reauthorize.")
        http = credentials.authorize(http=httplib2.Http())
        analytics[ank] = discovery.build('analytics', version, http=http)
    return analytics.get(ank)

@serverboards.rpc_method
def get_data(service_id, view, start, end):
    analytics = get_analytics(service_id)

    data = analytics.reports().batchGet(
          body={
            'reportRequests': [
            {
              'viewId': view,
              'dateRanges': [{'startDate': start, 'endDate': end}],
              'metrics': [{'expression': 'ga:sessions'}],
              'dimensions': [{"name":'ga:date'}]
            }]
          }
      ).execute()

    def decorate(datum):
        def date(d):
            return time.mktime((int(d[0:4]), int(d[4:6]), int(d[6:8]), 0,0,0, 0,0,0))
        return [date(datum['dimensions'][0]), datum['metrics'][0]['values'][0]]

    data = [decorate(x) for x in data['reports'][0]['data']['rows']]
    name = get_view_name(service_id, view) + " - " + "Sessions"

    return [{"name": name, "values" : data}]

@serverboards.rpc_method
def get_view_name(service_id, viewid):
    try:
        return next(x for x in get_views(service_id) if x["value"]==viewid)["name"]
    except:
        raise Exception("View not found")

views_cache=None
@serverboards.rpc_method
def get_views(service_id=None, service=None, **kwargs):
    print(service)
    assert service or service_id
    if not service_id:
        service_id=service["uuid"]
    global views_cache
    if views_cache:
        return views_cache
    analytics = get_analytics(service_id, 'v3')
    accounts = analytics.management().accountSummaries().list().execute()
    accounts = [
            {
                "name":"%s - %s"%(p['name'], pp['name']),
                "value": pp["id"]
            }
        for a in accounts['items']
        for p in a['webProperties']
        for pp in p['profiles']
        ]
    accounts.sort(key=lambda ac: ac['name'])
    views_cache=accounts
    return accounts


def test():
    aurl = authorize_url()
    assert aurl
    #analytics = connect_to_analytics()
    #assert analytics


    print("Success")

if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='test':
        test()
    else:
        serverboards.loop()
