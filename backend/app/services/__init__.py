"""The service layer. Every decision in the system lives here.

Thirteen services, and no SQL. A service reaches data only through the
repository, which is what makes the move to PostgreSQL a dialect change
rather than an audit of every file.

Cross service calls are enumerated, not free. Six exist:
    DealService      -> CheckEngine, before writing
    DealService      -> ApprovalRouter
    MatchService     -> CheckEngine, on a correction
    AdvisoryService  -> CheckEngine, at stage 3 and again at stage 5
    AmendmentService -> AccrualService
Anything else is a design change to argue about.

Phase one builds, in this order: ExposureCalculator, CheckEngine,
ApprovalRouter, DealService, QueueService and BreachService, RetestService,
OnboardingService, ExposureService.
"""
