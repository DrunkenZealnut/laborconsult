-- Q&A retrieval and voluntary feedback. Apply with an administrative DB role.
-- Private laborconsult schema only. No question/answer bodies are stored here.
BEGIN;
CREATE TABLE IF NOT EXISTS laborconsult.qa_retrieval_traces (
  conversation_id uuid PRIMARY KEY REFERENCES laborconsult.qa_conversations(id) ON DELETE CASCADE,
  trace_id uuid NOT NULL UNIQUE,
  items jsonb NOT NULL CHECK(jsonb_typeof(items)='array'),
  unidentified_selected integer NOT NULL DEFAULT 0 CHECK(unidentified_selected>=0),
  versions jsonb NOT NULL CHECK(jsonb_typeof(versions)='object'),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS laborconsult.answer_feedback (
  conversation_id uuid PRIMARY KEY REFERENCES laborconsult.qa_conversations(id) ON DELETE CASCADE,
  exposed_at timestamptz,
  positive boolean,
  reason text CHECK(reason IN ('legal_calculation_error','unclear','missing_answer','other')),
  voted_at timestamptz,
  versions jsonb NOT NULL CHECK(jsonb_typeof(versions)='object'),
  CHECK ((positive IS NULL AND reason IS NULL AND voted_at IS NULL) OR
         (positive IS NOT NULL AND voted_at IS NOT NULL AND exposed_at IS NOT NULL AND
          ((positive AND reason IS NULL) OR (NOT positive AND reason IS NOT NULL))))
);
-- A mismatched prior schema must abort, not leave a partially compatible migration.
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='laborconsult.answer_feedback'::regclass AND contype='f')
     OR NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='laborconsult.qa_retrieval_traces'::regclass AND contype='f') THEN
    RAISE EXCEPTION 'QA_QUALITY_SCHEMA_MISMATCH';
  END IF;
END $$;
ALTER TABLE laborconsult.qa_retrieval_traces ENABLE ROW LEVEL SECURITY;
ALTER TABLE laborconsult.answer_feedback ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON laborconsult.qa_retrieval_traces,laborconsult.answer_feedback FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT,INSERT ON laborconsult.qa_retrieval_traces TO service_role;
GRANT SELECT ON laborconsult.answer_feedback TO service_role;
DROP POLICY IF EXISTS qa_trace_service_read ON laborconsult.qa_retrieval_traces;
CREATE POLICY qa_trace_service_read ON laborconsult.qa_retrieval_traces FOR SELECT TO service_role USING(true);
DROP POLICY IF EXISTS qa_trace_service_insert ON laborconsult.qa_retrieval_traces;
CREATE POLICY qa_trace_service_insert ON laborconsult.qa_retrieval_traces FOR INSERT TO service_role WITH CHECK(true);
DROP POLICY IF EXISTS qa_feedback_service_read ON laborconsult.answer_feedback;
CREATE POLICY qa_feedback_service_read ON laborconsult.answer_feedback FOR SELECT TO service_role USING(true);
CREATE INDEX IF NOT EXISTS qa_trace_created_idx ON laborconsult.qa_retrieval_traces(created_at);
CREATE INDEX IF NOT EXISTS qa_feedback_exposed_idx ON laborconsult.answer_feedback(exposed_at);

CREATE OR REPLACE FUNCTION laborconsult.qa_feedback_record(
 p_conversation_id uuid,p_session_id text,p_kind text,p_positive boolean,p_reason text,p_versions jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=laborconsult,pg_temp AS $$
DECLARE old answer_feedback%ROWTYPE;
BEGIN
 -- Lock the parent first: exposure/vote concurrent calls serialize for one answer.
 PERFORM 1 FROM qa_conversations WHERE id=p_conversation_id AND session_id=p_session_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'FEEDBACK_OWNER'; END IF;
 IF p_kind IS NULL OR p_kind NOT IN ('exposure','vote') OR p_versions IS NULL OR jsonb_typeof(p_versions)<>'object' THEN
   RAISE EXCEPTION 'FEEDBACK_INVALID';
 END IF;
 IF p_kind='exposure' THEN
   IF p_positive IS NOT NULL OR p_reason IS NOT NULL THEN RAISE EXCEPTION 'FEEDBACK_INVALID'; END IF;
   INSERT INTO answer_feedback(conversation_id,exposed_at,versions) VALUES(p_conversation_id,now(),p_versions)
     ON CONFLICT(conversation_id) DO NOTHING;
 ELSE
   IF p_positive IS NULL OR (p_positive AND p_reason IS NOT NULL) OR
     (NOT p_positive AND (p_reason IS NULL OR p_reason NOT IN ('legal_calculation_error','unclear','missing_answer','other'))) THEN
       RAISE EXCEPTION 'FEEDBACK_INVALID';
   END IF;
   SELECT * INTO old FROM answer_feedback WHERE conversation_id=p_conversation_id;
   IF NOT FOUND OR old.exposed_at IS NULL THEN RAISE EXCEPTION 'FEEDBACK_NOT_EXPOSED'; END IF;
   IF old.versions<>p_versions THEN RAISE EXCEPTION 'FEEDBACK_VERSION'; END IF;
   IF old.positive IS NOT DISTINCT FROM p_positive AND old.reason IS NOT DISTINCT FROM p_reason THEN
     RETURN jsonb_build_object('saved',true);
   END IF;
   IF old.voted_at > now()-interval '10 seconds' THEN RAISE EXCEPTION 'FEEDBACK_RATE'; END IF;
   UPDATE answer_feedback SET positive=p_positive,reason=p_reason,voted_at=now() WHERE conversation_id=p_conversation_id;
 END IF;
 RETURN jsonb_build_object('saved',true);
END $$;
REVOKE ALL ON FUNCTION laborconsult.qa_feedback_record(uuid,text,text,boolean,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION laborconsult.qa_feedback_record(uuid,text,text,boolean,text,jsonb) TO service_role;

CREATE OR REPLACE FUNCTION laborconsult.qa_quality_summary(p_days integer DEFAULT 30)
RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=laborconsult,pg_temp AS $$
 WITH f AS (SELECT * FROM answer_feedback WHERE exposed_at>=now()-make_interval(days=>greatest(1,least(p_days,365)))),
 t AS (SELECT * FROM qa_retrieval_traces WHERE created_at>=now()-make_interval(days=>greatest(1,least(p_days,365)))),
 origins AS (SELECT item->>'corpus_origin' origin,count(*) candidates,
   count(*) FILTER(WHERE (item->>'selected_for_context')::boolean) supplied
   FROM t CROSS JOIN LATERAL jsonb_array_elements(items) item GROUP BY 1),
 reasons AS (SELECT reason,count(*) n FROM f WHERE positive=false GROUP BY reason),
 versions AS (SELECT versions,count(*) exposures,count(voted_at) votes,count(*) FILTER(WHERE positive) positive FROM f GROUP BY versions)
 SELECT jsonb_build_object(
   'feedback',jsonb_build_object('exposures',(SELECT count(*) FROM f),'votes',(SELECT count(voted_at) FROM f),
     'positive',(SELECT count(*) FROM f WHERE positive),'exploratory',(SELECT count(voted_at)<30 FROM f),
     'negative_reasons',COALESCE((SELECT jsonb_object_agg(reason,n) FROM reasons),'{}'::jsonb),
     'by_version',COALESCE((SELECT jsonb_agg(to_jsonb(v)) FROM versions v),'[]'::jsonb)),
   'retrieval',jsonb_build_object('answers',(SELECT count(*) FROM t),'by_origin',COALESCE((SELECT jsonb_agg(to_jsonb(o)) FROM origins o),'[]'::jsonb)),
   'interpretation','Context supply is not causal influence. Voluntary votes are not a representative satisfaction survey.');
$$;
REVOKE ALL ON FUNCTION laborconsult.qa_quality_summary(integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION laborconsult.qa_quality_summary(integer) TO service_role;
COMMIT;
