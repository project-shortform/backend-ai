import { useState } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { toast } from 'sonner';

axios.defaults.baseURL = 'http://localhost:5000';

export default function Dashboard() {
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState('');
  const [search, setSearch] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [uploadTab, setUploadTab] = useState('file');

  const [isUploading, setIsUploading] = useState(false);

  // 파일 업로드
  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    setIsUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    await axios.post('/api/upload', formData);
    toast.success('업로드 완료!');
    setFile(null);
    setIsUploading(false);
  };

  // URL 업로드
  const handleUrlUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url) return;
    setIsUploading(true);
    await axios.post('/api/upload_url', null, { params: { url } });
    toast.success('URL 업로드 완료!');
    setUrl('');
    setIsUploading(false);
  };

  // 검색
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!search) return;
    const res = await axios.get('/api/search', { params: { text: search } });
    setSearchResults(res.data);
    toast.success('검색 완료!');
  };

  return (
    <div className='space-y-8'>
      <Card>
        <CardHeader>
          <CardTitle>비디오 업로드</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs
            value={uploadTab}
            onValueChange={setUploadTab}
            className='w-full'
          >
            <TabsList className='mb-4'>
              <TabsTrigger value='file'>파일 업로드</TabsTrigger>
              <TabsTrigger value='url'>URL 업로드</TabsTrigger>
            </TabsList>
            <TabsContent value='file'>
              <form onSubmit={handleFileUpload} className='flex gap-2'>
                <Input
                  type='file'
                  accept='video/*'
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                />
                <Button type='submit' disabled={isUploading}>
                  {isUploading ? '업로드 중...' : '업로드'}
                </Button>
              </form>
            </TabsContent>
            <TabsContent value='url'>
              <form onSubmit={handleUrlUpload} className='flex gap-2'>
                <Input
                  type='url'
                  placeholder='비디오 URL 입력'
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
                <Button type='submit' disabled={isUploading}>
                  {isUploading ? '업로드 중...' : 'URL 업로드'}
                </Button>
              </form>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>비디오 검색</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSearch} className='flex gap-2'>
            <Input
              type='text'
              placeholder='검색어 입력'
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <Button type='submit' variant='secondary'>
              검색
            </Button>
          </form>
          {searchResults.length > 0 && (
            <ul className='mt-4 space-y-2'>
              {searchResults.map((item, idx) => (
                <li key={idx} className='flex items-center gap-2'>
                  <Link
                    to={`/video/${item.file_name}`}
                    className='text-blue-600 underline'
                  >
                    {item.file_name}
                  </Link>
                  <span className='text-xs text-muted-foreground'>
                    ({item.distance.toFixed(2)})
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
