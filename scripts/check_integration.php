<?php

declare(strict_types=1);

// Read-only contract test against real installed Harvest/Mediary bundles. No service container or paid requests.
require ($argv[1] ?? '/Users/tac/sites/harvest/vendor/autoload.php');
require __DIR__.'/../integrations/LocalPeriodicalTask.php';
use PdfTools\Integration\LocalPeriodicalTask;
use Survos\AiWorkflowBundle\Task\Analysis\PeriodicalStructureTask;
use App\Periodical\AltoParser;

foreach (glob(($argv[2] ?? __DIR__.'/../work/pilot/results').'/p*.json') as $file) {
    $r = json_decode(file_get_contents($file), true, flags: JSON_THROW_ON_ERROR);
    LocalPeriodicalTask::validateResult($r, $r['sourceSha256']);
    if (str_ends_with($file, '-alto.json')) {
        preg_match('/p(\d+)-/', $file, $m); $pageIndex = (int) $m[1] - 1;
        $alto = (new AltoParser())->parse(file_get_contents(__DIR__.'/../work/pilot/alto/'.($pageIndex+1).'.xml'), $r['width'], $r['height'], $pageIndex);
        $expected = array_map(static fn($b) => ['id'=>$b['id'],'text'=>$b['text'],'box'=>$b['box']], $alto['layout']['blocks']);
        $row = LocalPeriodicalTask::structureRequest($r, 'https://example.org/scan.jp2', 'cron-america/sn85059732', 'sn85059732-1914-11-29-ed-1', '1914-11-29', $pageIndex);
        if ($row['context']['periodicalPage']['blocks'] != $expected) { throw new RuntimeException('Existing AltoParser contract mismatch: '.$file); }
    }
    echo basename($file)." contract OK\n";
}
