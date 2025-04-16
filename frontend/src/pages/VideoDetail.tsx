import { useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import axios from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

axios.defaults.baseURL = 'http://localhost:5000';

export default function VideoDetail() {
  const { fileName } = useParams<{ fileName: string }>();
  const [info, setInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!fileName) return;
    setLoading(true);
    axios
      .get('/api/search', { params: { text: fileName } })
      .then((res) => {
        const found = res.data.find((item: any) => item.file_name === fileName);
        setInfo(found);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
  }, [fileName]);

  return (
    <div className='max-w-2xl mx-auto'>
      <Card>
        <CardHeader>
          <CardTitle>{fileName}</CardTitle>
        </CardHeader>
        <CardContent>
          <video
            src={`http://localhost:5000/uploads/${fileName}`}
            controls
            className='w-full mb-4 rounded'
          />
          {loading ? (
            <div className='flex items-center gap-2 text-muted-foreground'>
              <Loader2 className='animate-spin w-4 h-4' />
              임베딩 정보 불러오는 중...
            </div>
          ) : info ? (
            <div>
              <div className='font-bold mb-2'>임베딩 정보</div>
              <pre className='bg-muted p-2 rounded text-xs'>
                {JSON.stringify(info.metadata, null, 2)}
              </pre>
              <div className='text-xs text-muted-foreground mt-2'>
                distance: {info.distance}
              </div>
            </div>
          ) : (
            <div className='text-muted-foreground'>
              임베딩 정보를 찾을 수 없습니다.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
