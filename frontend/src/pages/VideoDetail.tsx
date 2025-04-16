import { useParams } from 'react-router-dom';
import { useEffect, useState } from 'react';
import axios from 'axios';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

axios.defaults.baseURL = 'http://localhost:5000';

export default function VideoDetail() {
  const { fileName } = useParams<{ fileName: string }>();
  const [info, setInfo] = useState<any>(null);

  useEffect(() => {
    if (!fileName) return;
    axios.get('/api/search', { params: { text: fileName } }).then((res) => {
      const found = res.data.find((item: any) => item.file_name === fileName);
      setInfo(found);
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
          {info && (
            <div>
              <div className='font-bold mb-2'>임베딩 정보</div>
              <pre className='bg-muted p-2 rounded text-xs'>
                {JSON.stringify(info.metadata, null, 2)}
              </pre>
              <div className='text-xs text-muted-foreground mt-2'>
                distance: {info.distance}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
