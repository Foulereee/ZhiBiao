from services.interpret.skills.tender_interpret_skill import TenderInterpretSkill
from services.interpret.skills.scoring_matrix_skill import ScoringMatrixSkill
from services.interpret.skills.risk_alert_skill import RiskAlertSkill
from services.interpret.skills.interpret_export_skill import InterpretExportSkill
from services.generate.skills.content_gen_skill import ContentGenSkill
from services.generate.skills.outline_gen_skill import OutlineGenSkill
from services.generate.skills.mandatory_req_extract_skill import MandatoryReqExtractSkill
from services.generate.skills.content_expand_skill import ContentExpandSkill
from services.generate.skills.structure_template_skill import StructureTemplateSkill, ScoreCoverageSkill
from services.generate.skills.knowledge_assist_skill import KnowledgeAssistSkill
from services.generate.skills.multi_agent_pipeline_skill import MultiAgentPipelineSkill
from services.check.skills.compliance_check_skill import ComplianceCheckSkill
from services.check.skills.pricing_check_skill import PricingCheckSkill
from services.check.skills.disqualification_check_skill import DisqualificationCheckSkill
from services.check.skills.qualification_check_skill import QualificationCheckSkill
from services.check.skills.fit_score_skill import FitScoreSkill
from services.check.skills.selfcheck_list_skill import SelfcheckListSkill
from services.check.skills.deposit_check_skill import DepositCheckSkill
from services.check.skills.signature_check_skill import SignatureCheckSkill
from services.check.skills.validity_check_skill import ValidityCheckSkill
from services.check.skills.consistency_check_skill import ConsistencyCheckSkill
from services.check.skills.duplicate_check_skill import DuplicateCheckSkill
from services.check.skills.doc_integrity_check_skill import DocIntegrityCheckSkill
from services.check.skills.mandatory_req_check_skill import MandatoryReqCheckSkill
from services.check.skills.whitelist_filter_skill import WhitelistFilterSkill
from services.check.skills.check_report_export_skill import CheckReportExportSkill
from services.check.skills.ai_text_check_skill import AITextCheckSkill
from services.check.skills.risk_score_skill import RiskScoreSkill
from services.check.skills.cross_check_skill import CrossCheckSkill
from services.check.skills.sample_report_check_skill import SampleReportCheckSkill
from services.check.skills.joint_bid_check_skill import JointBidCheckSkill
from services.check.skills.ebid_submit_check_skill import EbidSubmitCheckSkill
from services.check.skills.pricing_logic_check_skill import PricingLogicCheckSkill
from services.format.skills.docx_format_skill import DocxFormatSkill
from services.format.skills.pdf_export_skill import PdfExportSkill
from services.format.skills.revision_skill import RevisionSkill
from services.news.skills.news_crawler_skill import NewsCrawlerSkill, AISemanticFilterSkill, NotificationSkill
from services.generate.skills.ai_image_skill import AiImageSkill

from core.skill_engine.registry import SkillRegistry


def register_builtin_skills():
    registry = SkillRegistry.instance()

    registry.register(TenderInterpretSkill)
    registry.register(ScoringMatrixSkill)
    registry.register(RiskAlertSkill)
    registry.register(InterpretExportSkill)

    registry.register(ContentGenSkill)
    registry.register(OutlineGenSkill)
    registry.register(MandatoryReqExtractSkill)
    registry.register(ContentExpandSkill)
    registry.register(StructureTemplateSkill)
    registry.register(ScoreCoverageSkill)
    registry.register(KnowledgeAssistSkill)
    registry.register(MultiAgentPipelineSkill)

    registry.register(ComplianceCheckSkill)
    registry.register(PricingCheckSkill)
    registry.register(DisqualificationCheckSkill)
    registry.register(QualificationCheckSkill)
    registry.register(FitScoreSkill)
    registry.register(SelfcheckListSkill)
    registry.register(DepositCheckSkill)
    registry.register(SignatureCheckSkill)
    registry.register(ValidityCheckSkill)
    registry.register(ConsistencyCheckSkill)
    registry.register(DuplicateCheckSkill)
    registry.register(DocIntegrityCheckSkill)
    registry.register(MandatoryReqCheckSkill)
    registry.register(WhitelistFilterSkill)
    registry.register(CheckReportExportSkill)
    registry.register(AITextCheckSkill)
    registry.register(RiskScoreSkill)
    registry.register(CrossCheckSkill)
    registry.register(SampleReportCheckSkill)
    registry.register(JointBidCheckSkill)
    registry.register(EbidSubmitCheckSkill)
    registry.register(PricingLogicCheckSkill)

    registry.register(DocxFormatSkill)
    registry.register(PdfExportSkill)
    registry.register(RevisionSkill)

    registry.register(NewsCrawlerSkill)
    registry.register(AISemanticFilterSkill)
    registry.register(NotificationSkill)

    registry.register(AiImageSkill)
