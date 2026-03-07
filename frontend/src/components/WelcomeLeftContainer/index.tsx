import { ReactChild } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, Space, Typography } from 'antd';

import { Container, LeftContainer } from './styles';

const { Title } = Typography;

function WelcomeLeftContainer({
	version,
	children,
}: WelcomeLeftContainerProps): JSX.Element {
	const { t } = useTranslation();

	return (
		<Container>
			<LeftContainer direction="vertical">
				<Space align="center">
					<Title style={{ fontSize: '46px', margin: 0 }}>Observer Stack</Title>
				</Space>
				<Typography>{t('monitor_signup')}</Typography>
				<Card
					style={{ width: 'max-content' }}
					bodyStyle={{ padding: '1px 8px', width: '100%' }}
				>
					Observer Stack {version}
				</Card>
			</LeftContainer>
			{children}
		</Container>
	);
}

interface WelcomeLeftContainerProps {
	version: string;
	children: ReactChild;
}

export default WelcomeLeftContainer;
