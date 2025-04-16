import { Link } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

export default function Header() {
  return (
    <header className={cn('w-full border-b bg-background sticky top-0 z-50')}>
      <div className='container mx-auto flex items-center justify-between py-4'>
        <Link to='/' className='text-xl font-bold tracking-tight'>
          🎬 Video Uploader
        </Link>
        <nav className='flex gap-4'>
          <Button asChild variant='ghost'>
            <Link to='/'>대시보드</Link>
          </Button>
        </nav>
      </div>
    </header>
  );
}
