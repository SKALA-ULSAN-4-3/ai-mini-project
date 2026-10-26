import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/extra.css'
import './styles/refine.css'

const app = createApp(App)
app.use(createPinia()) // 로그인 상태 같은 공용 데이터 보관소(Pinia)
app.use(router)        // 화면 이동(주소 → 화면 연결)
app.mount('#app')
