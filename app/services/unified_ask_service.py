"""The shared LLM-only governed question workflow."""
from app.services.advanced_query_service import AdvancedQueryService
from app.services.llm_planner_service import LLMPlannerService


class UnifiedAskService:
    def __init__(self):self.engine=AdvancedQueryService();self.llm=LLMPlannerService()

    def ask(self,workspace,release_id,question,execute=True,previous_plan=None,constraints=None):
        if not isinstance(question,str) or not 2<=len(question.strip())<=500:raise ValueError('Question must contain 2–500 characters')
        if not self.llm.status()['ready']:
            raise ValueError('LLM_CONNECTION_REQUIRED: Verify and select Bedrock planning and verification models in Administration → AI Models. Offline answering is disabled.')
        schema=self.engine.schema(workspace,release_id)
        if previous_plan is not None:self.engine.compile(workspace,release_id,previous_plan)
        proposal,model=self.engine._llm(question,schema,previous_plan)
        base={'question':question,'release_id':release_id,'planner':'bedrock','model_id':model,'model_used':True,'executed':False,'columns':[],'rows':[],'row_count':0}
        if proposal.get('clarification'):return {**base,'status':'needs_clarification','answer':proposal['clarification'],'clarification':proposal['clarification']}
        plan=proposal['plan'];compiled=self.engine.compile(workspace,release_id,plan)
        self.engine.check_constraints(compiled,constraints)
        verified=self.llm.verify(question,proposal,compiled,schema,previous_plan)
        if not verified['passed']:return {**base,'status':'needs_clarification','answer':verified['clarification'],'clarification':verified['clarification'],'semantic_review':verified}
        result=self.engine.run(workspace,release_id,question,plan=plan,execute=execute)
        rows=result['rows'];dims=len(plan.get('dimensions',[]))
        chart='kpi' if dims==0 and len(rows)<=1 else 'bar' if dims==1 and len(rows)<=20 else 'table'
        answer=f'Returned {len(rows)} result rows using certified business definitions.' if result['executed'] else 'Validated read-only SQL preview.'
        return {**base,**result,'model_id':model,'model_used':True,'answer':answer,'chart_type':chart,'structured_plan':plan,
            'semantic_review':verified,'intent':proposal['intent'],
            'evidence':{'release_digest':schema['release_digest'],'approved_join_ids':compiled['join_evidence'],
                'metric_ids':compiled['metric_ids'],'concept_ids':compiled['concept_ids'],'plan_digest':compiled['plan_digest'],
                'certified_assets':[x['asset_id'] for x in compiled['tables']]},
            'notice':'LLM proposed and independently reviewed the plan; application enforced definitions, grain and read-only SQL.'}
