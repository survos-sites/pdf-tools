<?php

declare(strict_types=1);

namespace PdfTools\Integration;

use Survos\AiWorkflowBundle\Task\{AsTask, ObservationTaskInterface, TaskResult};
use Survos\AiWorkflowBundle\Task\Analysis\PeriodicalStructureTask;
use Survos\ClaimsBundle\Service\{RawClaim, RunMeta};
use Survos\DataContracts\Workflow\{ContextSubjectInterface, WorkflowSubjectInterface};
use Symfony\Contracts\HttpClient\HttpClientInterface;

/** App-level adapter. Mediary owns the existing Asset, dispatch, retries and claim persistence. */
#[AsTask('Local newspaper analysis on an existing scan; no remote OCR calls.', self::class, produces: ['ai:pageAnalysis'])]
final readonly class LocalPeriodicalTask implements ObservationTaskInterface
{
    public function __construct(private HttpClientInterface $http, private string $baseUrl = 'http://127.0.0.1:5013') {}
    public function getTask(): string { return 'periodical_local'; }
    public function getMeta(): array { return ['version' => 1, 'platform' => 'pdf-tools', 'model' => 'american-stories-onnx']; }
    public function supports(WorkflowSubjectInterface $subject): bool
    {
        return $subject instanceof ContextSubjectInterface && isset($subject->getWorkflowContext()['localPageAnalysis']);
    }
    public function run(WorkflowSubjectInterface $subject): TaskResult
    {
        if (!$this->supports($subject)) { throw new \InvalidArgumentException('Existing asset needs localPageAnalysis context.'); }
        $input = $subject->getWorkflowContext()['localPageAnalysis'];
        // imagePath and sha256 describe the existing, locally acquired scan; no new media identity.
        $result = $this->http->request('POST', rtrim($this->baseUrl, '/').'/v1/analysis', [
            'json' => $input, 'timeout' => 330, 'max_duration' => 340,
        ])->toArray();
        self::validateResult($result, $input['sha256']);
        return new TaskResult(
            claims: [new RawClaim('ai:pageAnalysis', $result, basis: 'Local source-preserving OCR/layout; candidate grouping, unreviewed')],
            meta: new RunMeta(model: 'american-stories-onnx', response: ['resultId' => $result['resultId'], 'engine' => $result['engine']]),
        );
    }

    public static function validateResult(array $result, string $expectedSha): void
    {
        if (!hash_equals($expectedSha, $result['sourceSha256']) || $result['coordinateSpace'] !== 'original-image-pixels' || $result['boxFormat'] !== 'xywh') {
            throw new \UnexpectedValueException('Source/coordinate mismatch in local analysis.');
        }
        $page = ['width' => $result['width'], 'height' => $result['height'], 'blocks' => $result['blocks']];
        PeriodicalStructureTask::validate($page, self::structure($result));
    }

    /** Exact existing grouping contract; retain illustration subtype without changing shared enums. */
    public static function structure(array $result): array
    {
        $groups = $result['groups'];
        foreach ($groups as &$group) {
            if ($group['kind'] === 'illustration_caption') { $group['subtype'] = 'illustration_caption'; $group['kind'] = 'other'; }
        }
        return ['groups' => $groups, 'unassignedBlockIds' => $result['unassignedBlockIds']];
    }

    /** Feed the same source blocks to the EXISTING PeriodicalStructureQueue if semantic grouping is requested. */
    public static function structureRequest(array $result, string $assetUrl, string $dataset, string $issueId, string $date, int $pageIndex): array
    {
        $page = ['issueId' => $issueId, 'date' => $date, 'pageIndex' => $pageIndex,
            'width' => $result['width'], 'height' => $result['height'],
            'blocks' => array_map(static fn (array $b): array => ['id' => $b['id'], 'text' => $b['text'], 'box' => $b['box']], $result['blocks'])];
        return ['dataset' => $dataset, 'assetUrl' => $assetUrl,
            'sourceHash' => hash('sha256', json_encode($page, JSON_THROW_ON_ERROR)),
            'context' => [PeriodicalStructureTask::INPUT => $page]];
    }
}
