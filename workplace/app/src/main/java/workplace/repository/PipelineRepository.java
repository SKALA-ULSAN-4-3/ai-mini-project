package workplace.repository;

import workplace.domain.PipelineEntry;
import java.util.List;
import java.util.Optional;

/** 저장 계약: 모든 연산을 인증된 사업자 범위로 제한. */
public interface PipelineRepository {
    PipelineEntry select(String user, String bidNo, String revision);
    Optional<PipelineEntry> approve(String user, String bidNo, String revision);
    List<PipelineEntry> findAll(String user);
}
