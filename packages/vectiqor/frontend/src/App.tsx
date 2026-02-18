import { Routes, Route } from 'react-router-dom'
import { AppLayout } from './components/layout/AppLayout'
import { SharedConversation } from './components/share/SharedConversation'
import { ManagePage } from './components/manage/ManagePage'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />} />
      <Route path="/share/:token" element={<SharedConversation />} />
      <Route path="/manage" element={<ManagePage />} />
    </Routes>
  )
}
