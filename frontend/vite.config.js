import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// ★ 서버 주소 두 개. 팀에서 확정된 주소로 바꾸세요.
// 팀이 Render에 올린 서버를 쓰려면 AUTH_BACKEND 에 그 주소(예: 'https://○○○.onrender.com')를 넣으세요.
// (Render 서버는 잠들어 있다가 첫 요청에 30~60초 걸릴 수 있어요. SERVICE_API_KEY 는 화면 코드에 절대 넣지 마세요.)
const AUTH_BACKEND = 'http://localhost:8080' // 가입·로그인·프로필 (/api/...)
const RAG_SERVER = 'http://localhost:8001'   // 공고·요약·채점·Q&A (가이드의 :8001)

export default defineConfig({
  plugins: [vue()],
  server: {
    // 4번 서버의 CORS(허용 출처) 기본값이 http://localhost:5174 라서 같은 포트로 맞춥니다. (다르면 로그인 요청이 거부될 수 있어요)
    port: 5174,
    strictPort: true, // 5174가 이미 쓰이고 있으면 다른 포트로 넘어가지 않고 멈춥니다.
    // 화면의 /api, /rag 요청을 각 서버로 대신 전달합니다. (CORS 오류 방지용)
    proxy: {
      '/api': { target: AUTH_BACKEND, changeOrigin: true },
      '/rag': { target: RAG_SERVER, changeOrigin: true, rewrite: (p) => p.replace(/^\/rag/, '') },
    },
  },
})
