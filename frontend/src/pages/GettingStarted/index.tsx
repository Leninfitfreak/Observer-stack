import { Typography } from 'antd';

import { GetStartedContent } from './renderConfig';
import DocSection from './Section';

function InstrumentationPage(): JSX.Element {
	return (
		<>
			<Typography>
				Observer Stack is ready. Send telemetry from your applications and start
				deriving insights.
			</Typography>
			{GetStartedContent().map((section) => (
				<DocSection key={section.heading} sectionData={section} />
			))}
		</>
	);
}

export default InstrumentationPage;
