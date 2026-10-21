import { Composition } from 'remotion'
import { RECAP_FRAMES, Recap } from './Recap'
import type { RecapProps } from './props'
import sample from './sample.json'
import { FPS, HEIGHT, WIDTH } from './theme'

/** One composition. Renders pass the week's recap with --props; the studio shows the fixture week. */
export function Root() {
  return <Composition id="Recap" component={Recap} durationInFrames={RECAP_FRAMES} fps={FPS} width={WIDTH} height={HEIGHT}
    defaultProps={sample as RecapProps} />
}
