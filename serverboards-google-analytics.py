#!/usr/bin/python3

import serverboards, tempfile, requests
import os, json, sys, time
import httplib2

from serverboards import rpc
from oauth2client import client
from apiclient.discovery import build
from urllib.parse import urlencode

import settings

DISCOVERY_URI = ('https://analyticsreporting.googleapis.com/$discovery/rest')
OAUTH_AUTH_URL="https://accounts.google.com/o/oauth2/auth"
OAUTH_AUTH_TOKEN_URL="https://accounts.google.com/o/oauth2/token"

CLIENT_SECRETS_JSON={
  "installed": {
    "client_id": settings.CLIENT_ID,
    "client_secret": settings.CLIENT_SECRET,
    "redirect_uris": [],
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://accounts.google.com/o/oauth2/token"
  }
}
SCOPES = ['https://www.googleapis.com/auth/analytics.readonly']

@serverboards.rpc_method
def authorize_url():
    params={
        "response_type" : "code",
        "client_id" : settings.CLIENT_ID,
        "redirect_uri" : settings.SERVERBOARDS_URL + "/static/serverboards.google.analytics/auth.html",
        "scope": 'https://www.googleapis.com/auth/analytics.readonly',
        #"state": SERVER_TOKEN
    }
    url = OAUTH_AUTH_URL+"?"+urlencode(params)

    print(url)
    return url

@serverboards.rpc_method
def store_code(code):
    """
    Stores the code and get a refresh token and a access token
    """
    params={
        "code": code,
        "client_id": settings.CLIENT_ID,
        "client_secret": settings.CLIENT_SECRET,
        "redirect_uri": settings.SERVERBOARDS_URL + "/static/serverboards.google.analytics/auth.html",
        "grant_type": "authorization_code",
    }
    response = requests.post(OAUTH_AUTH_TOKEN_URL, params)
    print(response.text, dir(response))
    js = response.json()
    if 'error' in js:
        raise Exception(js['error_description'])
    rpc.call("plugin.data_set", "serverboards.google.analytics", "authorization", js)
    return js

analytics = None
@serverboards.rpc_method
def test_get_analytics_data():
    return get_data('118766509', '2016-10-01', '2016-10-06')

@serverboards.rpc_method
def get_data(view, start, end):
    global analytics
    if not analytics:
        analytics_auth_code = rpc.call("plugin.data_get", "serverboards.google.analytics", "authorization")
        if not analytics_auth_code:
            raise Exception("Client not authorized yet")

        credentials = client.AccessTokenCredentials(analytics_auth_code["access_token"], "Serverboards/1.0")
        http = credentials.authorize(http=httplib2.Http())
        analytics = build('analytics', 'v4', http=http, discoveryServiceUrl=DISCOVERY_URI)

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

    return [{"name": "Sessions", "values" : data}]

def test():
    aurl = authorize_url()
    assert aurl
    print(store_code(settings.ANALYTICS_CODE))
    #analytics = connect_to_analytics()
    #assert analytics


    print("Success")

if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='test':
        test()
    else:
        serverboards.loop()
