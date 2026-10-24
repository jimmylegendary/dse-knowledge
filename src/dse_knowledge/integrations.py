"""Local native adapters for HAT schema validation and Melete experience memory."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
from typing import Any

from .config import Settings

HAT_SCHEMA_ROOT = Path('/home/jimmy/repos/hat-schema')
MELETE_CORE_SRC = Path('/home/jimmy/repos/melete/packages/melete-core/src')
MAX_HARDWARE_BYTES = 512 * 1024
MAX_HARDWARE_NODES = 5000
MAX_HARDWARE_DEPTH = 64
MAX_EXPERIENCE_CHARS = 16_384
MAX_SOURCE_IDS = 64


def _import_native(package: str, import_root: Path) -> Any:
    """Import an installed package or add only its explicitly allowed local root."""
    try:
        return importlib.import_module(package)
    except ModuleNotFoundError as error:
        if error.name != package and not (error.name or '').startswith(package + '.'):
            raise
        if not import_root.is_dir():
            raise
        root = str(import_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        importlib.invalidate_caches()
        return importlib.import_module(package)


def _bounded_tree(value: Any, *, max_nodes: int = MAX_HARDWARE_NODES) -> None:
    active: set[int] = set()
    count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal count
        if depth > MAX_HARDWARE_DEPTH:
            raise ValueError('hardware_tree_too_deep')
        if not isinstance(node, (dict, list)):
            return
        identity = id(node)
        if identity in active:
            raise ValueError('hardware_tree_cycle')
        count += 1
        if count > max_nodes:
            raise ValueError('hardware_tree_too_large')
        active.add(identity)
        values = node.values() if isinstance(node, dict) else node
        for child in values:
            walk(child, depth + 1)
        active.remove(identity)

    walk(value, 0)


class NativeIntegrations:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._hat_schema: Any | None = None
        self._melete: dict[str, Any] | None = None

    def _hat(self) -> Any:
        if self._hat_schema is None:
            self._hat_schema = _import_native('hat_schema', HAT_SCHEMA_ROOT)
        return self._hat_schema

    def _melete_api(self) -> dict[str, Any]:
        if self._melete is None:
            _import_native('melete', MELETE_CORE_SRC)
            self._melete = {
                'Engine': importlib.import_module('melete.engine').Engine,
                'config': importlib.import_module('melete.config'),
                'contracts': importlib.import_module('melete.contracts'),
            }
        return self._melete

    def capabilities(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            'hat_schema': {'available': False, 'validation': 'structural_only'},
            'melete': {
                'available': False, 'storage': 'local_sqlite', 'encoder_backend': 'native_hashing',
                'encoder_dimension': 256, 'separate_from_dse_embedding': True,
                'dse_embedding_fallback': False,
            },
            'hat_system_controller': {'integrated': False, 'reason': 'no_native_controller_adapter'},
        }
        try:
            hat = self._hat()
            result['hat_schema'].update(available=True, version=getattr(hat, '__version__', 'unknown'))
        except Exception as error:
            result['hat_schema']['reason'] = type(error).__name__
        try:
            melete = self._melete_api()
            package = importlib.import_module('melete')
            result['melete'].update(available=True, version=getattr(package, '__version__', 'unknown'))
        except Exception as error:
            result['melete']['reason'] = type(error).__name__
        return result

    def validate_hardware(self, source: str) -> dict[str, Any]:
        if not isinstance(source, str) or not source.strip():
            raise ValueError('source_must_be_nonempty_text')
        if len(source.encode('utf-8')) > MAX_HARDWARE_BYTES:
            raise ValueError('source_exceeds_size_limit')
        hat = self._hat()
        try:
            import yaml
            documents = list(yaml.safe_load_all(source))
        except Exception as error:
            return {
                'status': 'invalid_source', 'reason': 'parse_error',
                'error_type': type(error).__name__,
                'validation_scope': 'hat-schema-structural',
                'physical_feasibility': 'not_assessed',
                'native_version': getattr(hat, '__version__', 'unknown'),
            }
        if len(documents) != 1 or not isinstance(documents[0], dict):
            return {'status': 'invalid_source', 'reason': 'one_mapping_document_required',
                    'validation_scope': 'hat-schema-structural', 'physical_feasibility': 'not_assessed'}
        document = documents[0]
        try:
            _bounded_tree(document)
        except ValueError as error:
            return {'status': 'invalid_source', 'reason': str(error),
                    'validation_scope': 'hat-schema-structural', 'physical_feasibility': 'not_assessed'}
        if document.get('document_kind') in {'component', 'assembly'}:
            return {
                'status': 'requires_bundle', 'reason': 'native_resolver_requires_source_path_and_bundle_root',
                'validation_scope': 'hat-schema-structural', 'physical_feasibility': 'not_assessed',
                'native_version': getattr(hat, '__version__', 'unknown'),
            }
        try:
            twin = hat.load_twin(document)
            diagnostics = hat.validate_twin(twin)
        except Exception as error:
            return {
                'status': 'invalid_source', 'reason': 'native_validation_error',
                'error_type': type(error).__name__,
                'validation_scope': 'hat-schema-structural',
                'physical_feasibility': 'not_assessed',
                'native_version': getattr(hat, '__version__', 'unknown'),
            }
        rows = [
            {'level': item.get('level'), 'severity': item.get('severity'), 'message': item.get('msg')}
            for item in diagnostics
        ]
        errors = sum(item.get('severity') == 'error' for item in diagnostics)
        return {
            'status': 'structurally_valid' if errors == 0 else 'structural_errors',
            'validation_scope': 'hat-schema-structural',
            'physical_feasibility': 'not_assessed',
            'buildability': 'not_asserted',
            'native_version': getattr(hat, '__version__', 'unknown'),
            'diagnostics': {'errors': errors, 'warnings': sum(
                item.get('severity') == 'warning' for item in diagnostics), 'items': rows},
        }

    def _scope_and_config(self, api: dict[str, Any]) -> tuple[Any, Any]:
        contracts = api['contracts']
        user_id = self.settings.get('MELETE_USER_ID', 'dse-knowledge')
        namespace = self.settings.get('MELETE_NAMESPACE', 'dse_knowledge')
        scope = contracts.Scope(user_id=user_id, namespace=namespace)
        config = api['config'].MeleteConfig(
            data_dir=self.settings.data_root / 'melete',
            user_id=user_id,
            default_namespace=namespace,
            capture_external_experience=True,
            encoder=api['config'].EncoderConfig(
                backend='hashing', model_id='melete-native-hashing', model_revision='1',
                output_dimension=256, device='cpu',
            ),
            extractor=api['config'].ExtractorConfig(mode='rule'),
        )
        return scope, config

    @staticmethod
    def _validate_record(payload: dict[str, Any]) -> tuple[str, str, str, list[str], str, str]:
        if not isinstance(payload, dict):
            raise ValueError('payload_must_be_object')
        event_id, decision_id, text = payload.get('event_id'), payload.get('decision_id'), payload.get('text')
        if not all(isinstance(item, str) and item.strip() for item in (event_id, decision_id, text)):
            raise ValueError('event_id_decision_id_and_text_required')
        if len(event_id) > 256 or len(decision_id) > 256 or len(text) > MAX_EXPERIENCE_CHARS:
            raise ValueError('melete_record_exceeds_size_limit')
        event_type = payload.get('event_type', 'decision')
        if event_type not in {'decision', 'feedback', 'experiment_analysis', 'note'}:
            raise ValueError('unsupported_dse_event_type')
        actor = payload.get('actor') if 'actor' in payload else (
            'user' if event_type == 'feedback' else 'assistant')
        if not isinstance(actor, str) or actor not in {'assistant', 'user'}:
            raise ValueError('unsupported_actor')
        if event_type == 'feedback' and actor != 'user':
            raise ValueError('feedback_actor_must_be_user')
        source_ids = payload.get('source_event_ids', [])
        if not isinstance(source_ids, list) or len(source_ids) > MAX_SOURCE_IDS:
            raise ValueError('source_event_ids_must_be_bounded_list')
        if any(not isinstance(value, str) or not value or len(value) > 256 for value in source_ids):
            raise ValueError('invalid_source_event_id')
        return event_id, decision_id, text, list(dict.fromkeys(source_ids)), event_type, actor

    def _query(self, engine: Any, scope: Any, query: str, *, task_id: str) -> Any:
        contracts = self._melete_api()['contracts']
        return engine.query(contracts.QueryRequest(
            query_id='dse-q-' + task_id.rsplit('-', 1)[-1], task_id=task_id,
            goal='dse_knowledge_experience', scope=scope,
            payload=contracts.TextPayload(text=query), context={'task_kind': 'dse_knowledge'},
        ))

    @staticmethod
    def _searchability(receipt: Any, readout: Any) -> dict[str, Any]:
        receipt_ids = set(receipt.memory_ids)
        found = {item.memory_id for item in readout.items} & receipt_ids
        status = ('pending_embedding' if receipt.embedding_pending else
                  'trace_only' if receipt.status == 'trace_only' else
                  'searchable' if found else 'not_found')
        return {
            'status': status, 'receipt_status': receipt.status,
            'receipt_memory_ids': list(receipt.memory_ids), 'matched_memory_ids': sorted(found),
            'embedding_pending': receipt.embedding_pending,
            'dense_skipped': readout.metrics.dense_skipped,
            'dense_candidates': readout.metrics.dense_candidates,
            'lexical_candidates': readout.metrics.lexical_candidates,
            'retrieval_id': readout.retrieval_id, 'snapshot_seq': readout.snapshot_seq,
            'query_task_id': readout.frame.task_id if readout.frame else None,
            'frame_id': readout.frame.frame_id if readout.frame else None,
        }

    def observe(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_id, decision_id, text, source_ids, event_type, actor_name = self._validate_record(payload)
        api = self._melete_api()
        scope, config = self._scope_and_config(api)
        contracts = api['contracts']
        try:
            actor = contracts.Actor(actor_name)
        except ValueError:
            raise ValueError('unsupported_actor') from None
        outcome = None
        frame_feedback = None
        if payload.get('outcome') is not None and payload.get('frame_feedback') is not None:
            raise ValueError('provide_outcome_or_frame_feedback_not_both')
        if payload.get('outcome') is not None:
            outcome = contracts.Outcome.model_validate(payload['outcome'])
            if outcome.scope != scope:
                raise ValueError('outcome_scope_mismatch')
            outcome = outcome.model_copy(update={
                'source_event_ids': list(dict.fromkeys([*outcome.source_event_ids, event_id]))
            })
        if payload.get('frame_feedback') is not None:
            frame_feedback = contracts.FrameFeedback.model_validate(payload['frame_feedback'])
            if frame_feedback.scope != scope:
                raise ValueError('frame_feedback_scope_mismatch')
            frame_feedback = frame_feedback.model_copy(update={
                'evidence_refs': list(dict.fromkeys([*frame_feedback.evidence_refs, 'dse-event:' + event_id]))
            })
        structured = {
            'dse_record_type': event_type, 'decision_id': decision_id,
            'actor': actor.value,
            'source_event_ids': list(dict.fromkeys([*source_ids, event_id])),
            'provenance_status': 'provided_references_unverified' if source_ids else 'decision_event_only',
        }
        kind = contracts.ObservationKind.note
        observation = contracts.Observation(
            event_id=event_id, scope=scope, observed_at=payload.get('observed_at') or datetime.now(timezone.utc),
            actor=actor, kind=kind,
            payload=contracts.TextPayload(text=text, structured=structured),
            source_ref=contracts.SourceRef(
                source_id='dse-decision:' + decision_id, source_kind='dse_knowledge_' + event_type,
                external_id=decision_id,
            ),
            previous_event_id=payload.get('previous_event_id'),
            root_event_id=payload.get('root_event_id'), task_family='dse_knowledge',
            intervention_id=payload.get('intervention_id'),
        )
        engine = api['Engine'].open(config)
        try:
            context = contracts.IntakeContext(
                user_id=scope.user_id, namespace=scope.namespace, tool='dse-knowledge',
                actor=actor, task_id=decision_id,
            )
            receipt = engine.ingest(observation, context=context)
            feedback_receipt: dict[str, Any] = {'status': 'not_provided'}
            if outcome is not None:
                try:
                    result = engine.observe(outcome)
                    feedback_receipt = {
                        'type': 'outcome', 'status': result.status, 'outcome_id': result.outcome_id,
                        'journal_seq': result.journal_seq, 'memory_revision': result.memory_revision,
                        'linked_predictions': list(result.linked_predictions),
                    }
                except Exception as error:
                    feedback_receipt = {'type': 'outcome', 'status': 'error',
                                        'error_type': type(error).__name__}
            elif frame_feedback is not None:
                try:
                    result = engine.review_frame(frame_feedback)
                    feedback_receipt = {
                        'type': 'frame_feedback', 'status': 'reviewed',
                        'feedback_id': result.feedback_id, 'frame_id': result.frame_id,
                        'decision': result.decision, 'reason': result.reason,
                    }
                except Exception as error:
                    feedback_receipt = {'type': 'frame_feedback', 'status': 'error',
                                        'error_type': type(error).__name__}
            query_task_id = 'dse-melete-' + __import__('hashlib').sha256(event_id.encode()).hexdigest()[:20]
            try:
                readout = self._query(engine, scope, text, task_id=query_task_id)
                searchability = self._searchability(receipt, readout)
            except Exception as error:
                searchability = {'status': 'error', 'error_type': type(error).__name__,
                                 'receipt_status': receipt.status,
                                 'receipt_memory_ids': list(receipt.memory_ids)}
            return {
                'status': 'recorded', 'decision_id': decision_id,
                'provenance': {'event_id': event_id, 'source_event_ids': structured['source_event_ids'],
                               'source_ref': observation.source_ref.model_dump(mode='json'),
                               'actor': actor.value,
                               'reference_status': structured['provenance_status']},
                'receipt': {
                    'event_id': receipt.event_id, 'status': receipt.status,
                    'gate_label': receipt.gate_label, 'memory_ids': list(receipt.memory_ids),
                    'memory_revision': receipt.memory_revision, 'journal_seq': receipt.journal_seq,
                    'extraction_incomplete': receipt.extraction_incomplete,
                    'embedding_pending': receipt.embedding_pending,
                },
                'feedback_receipt': feedback_receipt, 'searchability': searchability,
                'melete_encoder_backend': 'native_hashing', 'melete_encoder_dimension': 256,
                'dse_embedding_fallback': False,
                'authority': 'advisory_memory_not_canonical_claim_acceptance',
            }
        finally:
            engine.close()

    def query_experiences(self, query: str) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > MAX_EXPERIENCE_CHARS:
            raise ValueError('query_must_be_bounded_nonempty_text')
        api = self._melete_api()
        scope, config = self._scope_and_config(api)
        engine = api['Engine'].open(config)
        try:
            task_id = 'dse-melete-' + __import__('hashlib').sha256(
                (query + datetime.now(timezone.utc).isoformat()).encode()
            ).hexdigest()[:20]
            readout = self._query(engine, scope, query, task_id=task_id)
            source_ids: dict[str, list[str]] = {}
            if readout.frame is not None and readout.frame.subgraph is not None:
                source_ids = {node.memory_id: list(node.source_event_ids)
                              for node in readout.frame.subgraph.nodes}
            return {
                'status': 'found' if readout.items else 'no_match', 'retrieval_id': readout.retrieval_id,
                'snapshot_seq': readout.snapshot_seq, 'return_format': readout.return_format,
                'items': [{
                    'memory_id': item.memory_id, 'version': item.version, 'role': item.role.value,
                    'text': item.text, 'epistemic_state': item.epistemic_state.value,
                    'applicability': dict(item.applicability), 'score': item.score,
                    'spans': [span.model_dump(mode='json') for span in item.spans],
                    'source_event_ids': source_ids.get(item.memory_id, []),
                } for item in readout.items],
                'metrics': readout.metrics.model_dump(mode='json'),
                'melete_encoder_backend': 'native_hashing', 'melete_encoder_dimension': 256,
                'dse_embedding_fallback': False,
                'authority': 'advisory_memory_not_canonical_claim_acceptance',
            }
        finally:
            engine.close()
