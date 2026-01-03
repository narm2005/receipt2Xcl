#!/bin/bash

uvicorn app.main:app --host 0.0.0.0 --port 10000

export GOOGLE_APPLICATION_CREDENTIALS_JSON="/Users/narmadhapalanisamy/PycharmProjects/receipt2Xcl/backend/google_cloud_credentials.json"
