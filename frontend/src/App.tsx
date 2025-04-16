import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Dashboard from '@/pages/Dashboard';
import VideoDetail from '@/pages/VideoDetail';
import Header from '@/components/Header';

function App() {
  return (
    <BrowserRouter>
      <Header />
      <div className='container mx-auto py-8'>
        <Routes>
          <Route path='/' element={<Dashboard />} />
          <Route path='/video/:fileName' element={<VideoDetail />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
