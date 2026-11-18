"""Verify current qualification values, original evidence offsets and unchanged history."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
from warehouse.load import ROOT,connect
from warehouse.release_build import records
from warehouse.qualifications import body_fields


def main():
    c=connect('recruitment_dw_dev_cd_v1')
    try:
        rid=c.execute("SELECT release_id FROM audit.publication_pointer WHERE channel='sample'").fetchval()
        rows=records(c,'''SELECT j.*,q.education_resolution_json as education_json,q.experience_resolution_json as experience_json
          FROM ads.release_job_detail j JOIN dwd.job_qualification_evidence q
           ON q.release_id=j.release_id AND q.date_key=j.date_key AND q.job_key=j.job_key WHERE j.release_id=?''',rid)
        previous=c.execute('SELECT TOP(1) previous_release_id FROM audit.publication_history WHERE release_id=? ORDER BY publication_id DESC',rid).fetchval()
        old=records(c,'''SELECT education_group,experience_group,COUNT_BIG(*) n FROM ads.release_job_detail
          WHERE release_id=? AND source='tencent' AND is_core=1 GROUP BY education_group,experience_group''',previous) if previous else []
    finally:c.close()
    assert len(rows)==200
    counters={};conflicts=[];anchors=0
    by_id={(j['source'],j['source_job_id']):j for j in rows}
    for source in ('tencent','netease'):
        core=[j for j in rows if j['source']==source and j['is_core']]
        assert len(core)==98
        counters[source]={'education':dict(Counter(j['education_group'] for j in core)),
          'experience':dict(Counter(j['experience_group'] for j in core)),
          'education_status':dict(Counter(json.loads(j['education_json'])['status'] for j in core))}
    assert counters['tencent']['experience']=={'1年以上':25,'2年以上':27,'3年以上':33,'5年以上':7,'8年以上':1,'不限':2,'冲突待确认':3}
    assert counters['tencent']['education']=={'本科':36,'硕士':12,'未注明':50}
    assert counters['tencent']['education_status']['preference_only']==2
    for identity,expected in {'2077312480664797184':'本科','1930438817001635840':'硕士','2110191895966826496':'本科'}.items():
        assert by_id[('tencent',identity)]['education_group']==expected
    for job in rows:
        fields={**json.loads(job['content_json']),**body_fields(job),
                'experience_raw':job['experience_raw'],'education_raw':job['education_raw']}
        for name in ('education','experience'):
            resolution=json.loads(job[name+'_json'])
            assert resolution['value']==job[name+'_group']
            assert resolution['rule_version']=='qualification-cn-1.0'
            assert resolution['record_ref'].endswith('#'+job['source_job_id'])
            assert resolution['raw_refs']
            for e in resolution['evidence']:
                original=fields.get(e['field']) or ''
                assert original[e['start']:e['end']]==e['text'],(job['source_job_id'],name,e)
                anchors+=1
            if name=='education' and resolution['status'] in ('not_stated','preference_only'):
                assert resolution['value']=='未注明'
                assert not any(e['strength']=='必需' for e in resolution['evidence'])
            if name=='education' and resolution['status']=='conflict':
                conflicts.append({'source':job['source'],'source_job_id':job['source_job_id'],
                    'structured':job['education_raw'],'evidence':resolution['evidence']})
    if previous==4:
        assert sum(x['n'] for x in old if x['education_group']=='未知')==98
        assert sum(x['n'] for x in old if x['experience_group']=='未映射')==93
    result={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'passed','release_id':rid,
      'normalization_version':'conformed-cn-1.1','qualification_rule_version':'qualification-cn-1.0',
      'current_core_groups':counters,'verbatim_anchors_checked':anchors,'source_postings':200,'core_postings':196,
      'old_release_id':previous,'previous_tencent_groups_preserved':old,'education_conflicts':conflicts,
      'note':'Core Tencent: 48 explicit required degrees; 50 with no hard degree resolved, including 2 preference-only. No missing value converted to unlimited.'}
    target=ROOT/'reports/verification/门槛字段整改_20261118.json'
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('status','release_id','current_core_groups','verbatim_anchors_checked')},ensure_ascii=False))


if __name__=='__main__':main()
