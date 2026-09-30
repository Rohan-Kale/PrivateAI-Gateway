"""Distinct frozen synthetic templates; not an independently blinded holdout."""
import base64
import hashlib
import json
from pathlib import Path
import random
import string
from experiments.common import write_report


def build():
    rng=random.Random(849217);cases=[]
    token=lambda n:''.join(rng.choice(string.ascii_letters+string.digits) for _ in range(n))
    encode=lambda s:base64.b64encode(s.encode()).decode()
    url=lambda s:''.join('%%%02X'%ord(c) for c in s)
    for i in range(40):
        secret='sk-'+token(37); opaque=token(47)
        jwt=encode('{"alg":"HS512","typ":"JWT"}').rstrip('=')+'.'+encode(json.dumps({'aud':'synthetic-validation','sub':token(9)})).rstrip('=')+'.'+token(43)
        private='-----BEGIN EC PRIVATE KEY-----\n'+token(70)+'\n-----END EC PRIVATE KEY-----'
        positives=[('quoted_key',['Review "'+secret+'"'],[secret]),
                   ('all_percent',[url(secret)],[url(secret),secret]),
                   ('nested_base64',[encode(encode(secret))],[encode(encode(secret)),encode(secret),secret]),
                   ('base64_url',[encode(url(secret))],[encode(url(secret)),url(secret),secret]),
                   ('jwt_context',['Authorization: Bearer '+jwt],[jwt]),
                   ('encoded_private',[encode(private)],[encode(private),private]),
                   ('three_messages',[secret[:5],secret[5:17],secret[17:]],[secret]),
                   ('unicode_split',['Résumé 🌍 '+secret[:8],secret[8:]],[secret]),
                   ('assignment',['access-token: "'+opaque+'"'],[opaque]),
                   ('opaque_unlabeled',[opaque],[opaque])]
        negatives=[('bare_identifier',token(47)),('encoded_prose',encode('Please explain the deployment process.')),
                   ('placeholder','password=YOUR_PASSWORD_HERE'),('dotted_prose','release.segment.identifier'),
                   ('url_prose',url('ordinary documentation')),('public_email','Public contact: docs@example.org')]
        for family,contents,needles in positives:
            cases.append({'id':f'{family}-{i}','family':family,'label':'secret','messages':[{'role':'user','content':s} for s in contents],'exposure_needles':needles})
        for family,content in negatives:
            cases.append({'id':f'{family}-{i}','family':family,'label':'benign','messages':[{'role':'user','content':content}],'exposure_needles':[]})
    rng.shuffle(cases)
    return {'schema_version':1,'name':'synthetic-validation-v2','seed':849217,'synthetic_only':True,'held_out':False,'cases':cases}


if __name__=='__main__':
    data=build();root=Path('experiments/fixtures/validation-v2');path=root/'corpus.json'
    if path.exists():raise SystemExit('refusing to overwrite frozen validation corpus')
    manifest={'name':data['name'],'cases':len(data['cases']),'canonical_sha256':hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()}
    existing=root/'manifest.json'
    if existing.exists() and json.loads(existing.read_text())!=manifest:raise SystemExit('validation generator changed after freezing')
    write_report(path,data)
    if not existing.exists():write_report(existing,manifest)
