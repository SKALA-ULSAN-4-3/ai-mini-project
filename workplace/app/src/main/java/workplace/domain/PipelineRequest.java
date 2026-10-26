package workplace.domain;

/** 요청 DTO: 공고 식별자 수신, 사용자 식별은 JWT 사용. */
public record PipelineRequest(String bidNo, String revision) { }
