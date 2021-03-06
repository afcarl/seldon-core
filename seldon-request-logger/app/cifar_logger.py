from flask import Flask, request
import numpy as np
import json
import logging
import sys
import log_helper

MAX_PAYLOAD_BYTES = 300000
app = Flask(__name__)
print('starting cifar logger')
sys.stdout.flush()

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)


@app.route("/", methods=['GET','POST'])
def index():

    request_id = log_helper.extract_request_id(request.headers)
    type_header = request.headers.get(log_helper.TYPE_HEADER_NAME)
    message_type = log_helper.parse_message_type(type_header)
    index_name = log_helper.build_index_name(request.headers)

    body = request.get_json(force=True)

    # max size is configurable with env var or defaults to constant
    max_payload_bytes = log_helper.get_max_payload_bytes(MAX_PAYLOAD_BYTES)

    body_length = request.headers.get(log_helper.LENGTH_HEADER_NAME)
    if body_length and int(body_length) > int(max_payload_bytes):
        too_large_message = 'body too large for '+index_name+"/"+log_helper.DOC_TYPE_NAME+"/"+ request_id+ ' adding '+message_type
        print()
        sys.stdout.flush()
        return too_large_message

    if not type(body) is dict:
        body = json.loads(body)

    # print('RECEIVED MESSAGE.')
    # print(str(request.headers))
    # print(str(body))
    # print('----')
    # sys.stdout.flush()

    es = log_helper.connect_elasticsearch()


    try:

        #now process and update the doc
        doc = process_and_update_elastic_doc(es, message_type, body, request_id,request.headers, index_name)

        return str(doc)
    except Exception as ex:
        print(ex)
    sys.stdout.flush()
    return 'problem logging request'


def process_and_update_elastic_doc(elastic_object, message_type, message_body, request_id, headers, index_name):

    if message_type == 'unknown':
        print('UNKNOWN REQUEST TYPE FOR '+request_id+' - NOT PROCESSING')
        sys.stdout.flush()

    #first do any needed transformations
    new_content_part = process_content(message_type, message_body)

    #set metadata specific to this part (request or response)
    log_helper.field_from_header(content=new_content_part,header_name='ce-time',headers=headers)
    log_helper.field_from_header(content=new_content_part, header_name='ce-source', headers=headers)

    upsert_body= {
        "doc_as_upsert": True,
        "doc": {
            message_type: new_content_part
        }
    }

    log_helper.set_metadata(upsert_body['doc'],headers,message_type,request_id)

    new_content = elastic_object.update(index=index_name,doc_type=log_helper.DOC_TYPE_NAME,id=request_id,body=upsert_body,retry_on_conflict=3,refresh=True,timeout="60s")
    print('upserted to doc '+index_name+"/"+log_helper.DOC_TYPE_NAME+"/"+ request_id+ ' adding '+message_type)
    sys.stdout.flush()
    return str(new_content)

# take request or response part and process it by deriving metadata
def process_content(message_type,content):

    if content is None:
        print('content is empty')
        sys.stdout.flush()
        return content

    #if we have dataType then have already parsed before
    if "dataType" in content:
        print('dataType already in content')
        sys.stdout.flush()
        return content

    requestCopy = content.copy()

    if message_type == 'request':
        # we know this is a cifar10 image
        content["dataType"] = "image"
        requestCopy["image"] = decode(content)
        if "instances" in requestCopy:
            del requestCopy["instances"]

    return requestCopy


def decode(X):
    X=np.array(X["instances"])
    X=np.transpose(X, (0,2, 3, 1))
    img = X/2.0 + 0.5
    return img.tolist()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)