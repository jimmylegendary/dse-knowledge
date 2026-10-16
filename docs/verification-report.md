# 설계 패키지 실제 검증 기록

> 이 문서는 2026-10-16 원본 설계 패키지의 역사적 검증 기록이다. 공개본은 링크·환경 경로·내부 요청 metadata를 조정했으므로 아래 원본 hash는 공개본의 hash와 다를 수 있다. 코드의 개인 환경 경로도 `<planning-bundle>`로 표시했다. 공개본 검증은 [publication-report.md](https://github.com/jimmylegendary/dse-knowledge/blob/main/docs/publication-report.md)를 따른다.

검증 시각: 2026-10-15 19:10:09 UTC (KST 2026-10-16). 범위: 설계·계획 문서와 후보 점수 데이터. 제품 runtime·cloud 환경의 검증 결과가 아니다.

## 결과

- 문서 검증 항목 **21 통과 / 0 실패**.
- Source family 40개, 기술·구성·알고리즘 후보 평가 73개, CSV 113행의 key·점수·공식 URL 일치.
- 실행 phase P1–P5 × 11개 capability = 55개 비어 있지 않은 coverage 셀.
- P1 task 4개와 P2–P5 상세 작업 패키지 16개. 후속 패키지 각각 파일·입력·출력·acceptance·future command 존재.
- 절대 로컬 링크 42개와 파일명 라벨을 검사했다. 이 보고서 생성 후 예외 없는 닫힘 검사에서도 42개 링크 오류 0건, 23개 artifact hash 불일치 0건을 확인했다.
- Artifact 23개를 검사했으며, 이 보고서 생성 후 전체는 24개다. 모두 Markdown/JSON/CSV이며 product code·IaC 파일은 없다.

보고서 생성 후 실제 출력: `files=24, markdown=16, json=6, csv=2, checked_local_links=42, link_errors=[], artifact_hashes_checked=23, hash_errors=[]`. 추가 검사는 context-mode Python으로 fenced code를 제외한 Markdown 링크를 다시 읽고 SHA-256을 직접 재계산했다.

## 실행 도구와 실제 출력

실행: `mcp__context_mode__ctx_execute(language="python", code=<아래 코드>)`. 파일을 읽어 JSON/CSV/Markdown을 검증했으며 sandbox에서 파일을 쓰지 않았다. 결과 artifact는 native apply_patch로 기록했다.

```text
{
  "passed": 21,
  "failed": 0,
  "counts": {
    "source_families": 40,
    "technology_config_algorithm_candidates": 73,
    "csv_rows": 113,
    "local_links": 42,
    "phase_cells": 55,
    "later_phase_packages": 16,
    "existing_files": 23,
    "files_after_report": 24
  },
  "errors": []
}
```

Git 확인 command: `git rev-parse --show-toplevel`, working directory `<planning-bundle>`. 실제 exit code 128; 출력 `fatal: not a git repository (or any of the parent directories): .git`. 이 디렉터리는 Git 저장소가 아니므로 commit SHA는 없다. 저장소를 새로 만들거나 commit하지 않았다. Git metadata 부재는 위 문서 검증 21개 항목과 별개다.

## 항목별 결과

| 검증 항목 | 결과 |
|---|---|
| candidate JSON parse | PASS |
| candidate IDs unique within research context | PASS |
| candidate schema/range/arithmetic | PASS |
| source count | PASS |
| technology/configuration/algorithm count | PASS |
| source metadata fields | PASS |
| CSV rows complete | PASS |
| CSV scores and current URLs match JSON | PASS |
| Markdown scorecards cover all candidates | PASS |
| absolute existing local links | PASS |
| local file link labels | PASS |
| 11 capabilities across P1-P5, 55 nonempty cells | PASS |
| P0 full design progression | PASS |
| P1 task count | PASS |
| 16 later-phase packages and contracts | PASS |
| Superpowers workflow coverage | PASS |
| combination score arithmetic | PASS |
| reviewed cloud arithmetic anchors | PASS |
| Jev advisory record | PASS |
| artifact-only file extensions | PASS |
| P1 onboarding and unsupported negative case | PASS |

## 독립 review와 master 확인

Source·storage/retrieval·cloud/operations·models/ingestion을 독립 worker가 조사하고 서로 다른 worker가 검토했다. 새 builder reviewer가 전체 spec·계약·phase 계획을 읽고, 마지막 신규 모델 onboarding 모호함의 수정까지 closed로 확인했다.

Master는 기존 HAT/Melete source의 주요 계약을 직접 읽고, 후보 점수를 재계산하고, cross-document 역할·ACL·비용 가정을 통합했다. Neo4j 정본/파생 구분, ACL epoch, 미측정 local TCO, ACM 권리 출처, OpenSearch mode별 비용, Spanner replica 산식, RPO/RTO, P1 onboarding을 보완했다.

## 검증의 한계

- source catalog는 조사 계획과 공식 근거이며 corpus를 실제 구축하지 않았다.
- DB·embedding·retrieval·DSE 성능은 아직 측정하지 않았다. 점수는 잠정 prior다.
- cloud 설정·provisioning·secret 등록·대량 수집·HAT campaign·Melete 실제 ingest를 실행하지 않았다.
- 제품 test 실행 수는 0이다. 위 PASS는 문서·데이터 계약의 정적 정합성 검사이며 실행 기능 통과가 아니다.
- 문서 구조 검사와 독립 review가 모든 설계 오류의 부재를 보장하지 않는다. 운영 입력과 future acceptance는 그대로 유지한다.

## 검증 코드

다음은 마지막 검증에 전달한 실제 코드다. 보고서 생성 직전의 artifact 집합을 검사했으며 재실행 시 file/link count는 보고서의 자기 링크 등으로 달라질 수 있다.

```python
from pathlib import Path
import json,csv,re,hashlib
base=Path('<planning-bundle>')
checks=[];errors=[];counts={}
def check(name,ok,detail=''):
 checks.append({'name':name,'pass':bool(ok),'detail':detail})
 if not ok:errors.append({'name':name,'detail':detail})
w={'quality':25,'fit':20,'provenance':20,'operability':15,'portability':10,'economics':10}
sw={'relevance':30,'authority':25,'extractability':15,'rights':15,'freshness':10,'diversity':5}
items={};source_count=0;tool_count=0;record_errors=[];duplicates=[]
json_files=sorted((base/'research').glob('*.json'))
for p in json_files:
 d=json.loads(p.read_text());rows=d['candidates'];weights=sw if p.name.startswith('01-') else w;seen=set()
 for r in rows:
  key=p.name[:2]+':'+r['id']
  if key in seen:duplicates.append(key)
  seen.add(key)
  if set(r['scores'])!=set(weights):record_errors.append(key+':keys');continue
  if not all(isinstance(v,(int,float)) and 0<=v<=5 for v in r['scores'].values()):record_errors.append(key+':range')
  total=round(sum(weights[k]*r['scores'][k]/5 for k in weights),2)
  if 'total' in r and abs(r['total']-total)>1e-8:record_errors.append(key+':total')
  items[key]=(r,total,weights)
  if p.name.startswith('01-'):source_count+=1
  else:tool_count+=1
check('candidate JSON parse',len(json_files)==5,str(len(json_files)))
check('candidate IDs unique within research context',not duplicates,str(duplicates))
check('candidate schema/range/arithmetic',not record_errors,str(record_errors))
check('source count',source_count==40,str(source_count))
check('technology/configuration/algorithm count',tool_count==73,str(tool_count))
source_required=['url','extract','formats','metadata','access','refresh','quality','phase_coverage']
missing=[key+':'+field for key,(r,_,__) in items.items() if key.startswith('01:') for field in source_required if not r.get(field)]
check('source metadata fields',not missing,str(missing))
csv_errors=[];csv_count=0
for f in ['tool-scores.csv','source-scores.csv']:
 rows=list(csv.DictReader((base/'docs'/f).open()));csv_count+=len(rows)
 for row in rows:
  key=row['key']
  if key not in items:csv_errors.append(key+':absent');continue
  r,total,weights=items[key]
  if abs(float(row['score_100'])-total)>1e-8:csv_errors.append(key+':total')
  if any(float(row[k])!=r['scores'][k] for k in weights):csv_errors.append(key+':raw')
  current_url=r.get('url',(r.get('source_urls') or [''])[0])
  if row['official_url']!=current_url:csv_errors.append(key+':url')
check('CSV rows complete',csv_count==len(items),str(csv_count))
check('CSV scores and current URLs match JSON',not csv_errors,str(csv_errors))
score_md=(base/'docs/scorecards.md').read_text()
not_scored=[key for key in items if key+' · ' not in score_md]
check('Markdown scorecards cover all candidates',not not_scored,str(not_scored))
link_errors=[];label_errors=[];links=0
report=base/'docs/verification-report.md'
for p in base.rglob('*.md'):
 for label,target in re.findall(r'\[([^\]]+)\]\(([^\n]+?)\)',p.read_text()):
  target=target.strip('<>')
  if target.startswith(('http://','https://','mailto:','#')):continue
  links+=1
  if not target.startswith('/'):link_errors.append(str(p)+':relative:'+target);continue
  raw=re.sub(r':\d+$','',target.split('#')[0]);dest=Path(raw)
  if not dest.exists() and dest!=report:link_errors.append(str(p)+':missing:'+raw)
  if label!=dest.name:label_errors.append(str(p)+':label:'+label)
check('absolute existing local links',not link_errors,str(link_errors))
check('local file link labels',not label_errors,str(label_errors))
plan=(base/'docs/superpowers/plans/2026-10-16-dse-resolution-plan.md').read_text()
matrix=plan.split('## 2. Phase × 전체 capability')[1].split('## 3.')[0]
matrix_rows=[l for l in matrix.splitlines() if l.startswith('|') and not l.startswith('|---') and not l.startswith('| 영역')]
cells_ok=len(matrix_rows)==11 and all(len([x for x in l.split('|')[1:-1]])==6 and all(x.strip() for x in l.split('|')[2:-1]) for l in matrix_rows)
check('11 capabilities across P1-P5, 55 nonempty cells',cells_ok,str(len(matrix_rows)))
check('P0 full design progression',all('P0.'+x in plan for x in 'ABCD'))
check('P1 task count',len(re.findall(r'^### Task [1-4]\.',plan,re.M))==4)
packages=(base/'docs/phase-work-packages.md').read_text()
parts=re.split(r'^### (P[2-5]-[A-D]) ',packages,flags=re.M)
package_errors=[]
for i in range(1,len(parts),2):
 ident=parts[i];body=parts[i+1]
 for token in ['**Files:**','**Consumes:**','**Produces:**','**Acceptance:**','**Future verification:**']:
  if token not in body:package_errors.append(ident+':'+token)
check('16 later-phase packages and contracts',len(parts[1::2])==16 and not package_errors,str(package_errors))
skills=['using-superpowers','brainstorming','writing-plans','subagent-driven-development','requesting-code-review','receiving-code-review','verification-before-completion']
check('Superpowers workflow coverage',all(s in plan for s in skills))
combo={'A':[4,5,5,3,4,3],'B':[4,4,5,4,2,3],'C':[4,4,5,3,3,3],'D':[4,4,4,2,5,3]}
totals={k:sum(a*b/5 for a,b in zip(v,w.values())) for k,v in combo.items()}
check('combination score arithmetic',totals=={'A':83,'B':78,'C':77,'D':74},str(totals))
cloud=(base/'research/03-cloud-operations.md').read_text()
check('reviewed cloud arithmetic anchors',all(x in cloud for x in ['350.40','175.20','89.79']) and round(.041*3*730,2)==89.79)
advice=json.loads((base/'docs/decision-advice.json').read_text())
check('Jev advisory record',advice.get('advisory_only') and 'request' in advice and 'result' in advice)
allfiles=[p for p in base.rglob('*') if p.is_file()]
check('artifact-only file extensions',all(p.suffix in {'.md','.json','.csv'} for p in allfiles))
check('P1 onboarding and unsupported negative case',all(x in plan for x in ['ModelVersion onboarding','미지원 모델/연산']))
counts={'source_families':source_count,'technology_config_algorithm_candidates':tool_count,'csv_rows':csv_count,'local_links':links,'phase_cells':55,'later_phase_packages':16,'existing_files':len(allfiles),'files_after_report':len(allfiles)+(0 if report.exists() else 1)}
hashes={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(allfiles) if p!=report}
out={'checks':checks,'passed':sum(c['pass'] for c in checks),'failed':sum(not c['pass'] for c in checks),'counts':counts,'errors':errors,'sha256':hashes}
print('__AUDIT_JSON_START__')
print(json.dumps(out,ensure_ascii=False))
print('__AUDIT_JSON_END__')

```

## 산출물 SHA-256

이 보고서의 자기 hash를 제외한 23개 artifact hash다. 문서 개정 시 이 검증 revision과 달라진 것을 확인할 수 있다.

| 파일 | SHA-256 |
|---|---|
| `CONTEXT.md` | `aa47125dbd3c822515559986b98840c0b88ef6d2063bd5655bc805b4f4025cbd` |
| `README.md` | `de2800d2c569ed8d8f24ee7bad405aac1de54e01d739f8bc2d7215d17d945a0a` |
| `docs/data-contracts.md` | `04d9b99db392e5925ea2eccd58d202615e381fe1df6fce1cb58f7f5ca09f35cb` |
| `docs/decision-advice.json` | `d2d60f7743f8c4220a3e9245874abd8776da628138a51bf62d6ecd4325709ecd` |
| `docs/decisions-and-open-inputs.md` | `0d7fccd1532c6c857d2f64cbf51ab20b29f27faa7667d33be66bf74e0740b4d3` |
| `docs/phase-work-packages.md` | `a23a3875ff611c2f9a33d21fd9acc727684058736543a69342c78dccce59ff0f` |
| `docs/recommendation-and-selection.md` | `047cc535643fe1cc2af3e30ddb90a9a4d6fc3cabf35edccb57da9bccc89a06a4` |
| `docs/retrieval-and-decision.md` | `821f8e1d5d0ae3023d4d7dccab54cbc4d3599df7515db9603015b036d316a6f4` |
| `docs/scorecards.md` | `a6854c04f5b4e4d4a7432c48d7028ca78bae3bb461c307a63bd9db4bbbf0fdd6` |
| `docs/source-scores.csv` | `bcf36aea1ebff14d4e282a721ee12e56701fa01c602a5448342e06596e16cfb1` |
| `docs/superpowers/plans/2026-10-16-dse-resolution-plan.md` | `fa63da4e930510168b38cef3960e91a266e296c09b14686fa5dd83671fe2b4fa` |
| `docs/superpowers/specs/2026-10-16-dse-knowledge-system-design.md` | `a008cf71f503ee298cdaaa4ef0390768d03ecfb09bc51278d61be6b5f242df00` |
| `docs/tool-scores.csv` | `a8c796d396209d2f5dbd3080e3c9ffc3226381e26bf1d17c1df00f99c0a57f40` |
| `docs/validation-and-governance.md` | `4cbf99121fd6fe7866eeb361da7bc3fae22ce5e5cf7549209f05782a20b70e00` |
| `research/01-source-catalog.json` | `c5b12ce271bf7cffdd0538592951d7d291a5f3019259e23c49987d4ca7964fbf` |
| `research/01-source-catalog.md` | `4a9119e328fab486750a5a51eb626b8b9a34f3420ddc1ee8e99347589774e7ca` |
| `research/02-storage-retrieval.json` | `c8ff494912a9a9ad2743e52cec3f1c95e73c67eb6af7cd9fa61dc553b6c3a8e1` |
| `research/02-storage-retrieval.md` | `cc2b3ecfcb79790e0d019d6d5935983e5b7e8e94c9217901ff3d8ebe20c7618e` |
| `research/03-cloud-operations.json` | `4d43e27b16c8f95bbd7d1e25e851104e612a1013535ac225318cfe41e878b282` |
| `research/03-cloud-operations.md` | `3958b151ba692f274a414b604a723ed8ebf99aa669838f6274c88103d73a1e7b` |
| `research/04-models-ingestion-evaluation.json` | `401223b5bc4f8f6840562ab09f0d5bebef1977ca3b8cb7e994db3228ab18ca54` |
| `research/04-models-ingestion-evaluation.md` | `ae1100d3e1a2b0ba1ea817c56e811be31970260fde020eb41eaa8ae3c846053c` |
| `research/05-dse-search-candidates.json` | `8d440728b1e96d9322bc4bd25302d8fc375b0f9efa370804e19fa6caac516155` |
