package workplace.service;

import workplace.domain.PipelineEntry;
import workplace.domain.PipelineRequest;
import workplace.exception.ConflictException;
import workplace.exception.ValidationException;
import workplace.repository.PipelineRepository;
import java.util.List;

/** 진행 상태 서비스: 입력 검증, 선택 후 승인 정책. */
public final class PipelineService {
    private final PipelineRepository repository;

    public PipelineService(PipelineRepository repository) {
        this.repository = repository;
    }

    public PipelineEntry save(String user, PipelineRequest request, boolean approval) {
        if (request == null) {
            throw new ValidationException("요청 본문이 필요합니다.");
        }
        String bidNo = BidIds.bidNo(request.bidNo());
        // 차수 필수: 누락 방지, 문자열의 앞자리 0 보존.
        if (request.revision() == null || request.revision().isBlank()) {
            throw new ValidationException("revision 문자열이 필요합니다.");
        }
        String revision = BidIds.revision(request.revision());
        if (!approval) {
            return repository.select(user, bidNo, revision);
        }
        return repository.approve(user, bidNo, revision)
                .orElseThrow(() -> new ConflictException("선택된 공고만 승인할 수 있습니다."));
    }

    public List<PipelineEntry> list(String user) {
        return repository.findAll(user);
    }
}
